"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ConversationProvider, useConversation, useConversationClientTool } from "@elevenlabs/react";
import Mascot from "./mascot";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Question = {
  id: string; original_text: string; simplified_question: string; help_text?: string;
  input_type: string; options: string[]; required: boolean;
  source_reference?: { page?: number | null; section?: string | null } | null;
};
type NextState = {
  session_id: string; revision: number; status: "question" | "complete" | "blocked";
  question: Question | null; progress: Record<string, number>;
};
type Learned = { term: string; explanation: string; example: string };
type Past = { id: string; question: string; answer: string | null };

/** Readable form of a saved answer (multichoice answers are stored as JSON lists). */
function showAnswer(value: string | null) {
  if (!value?.trim()) return null;
  try { const list = JSON.parse(value); if (Array.isArray(list)) return list.join(", "); } catch {}
  return value;
}

/** Calls an /agent endpoint and turns errors into text the agent can act on, instead of throwing. */
async function tool(path: string, init?: RequestInit) {
  const response = await fetch(`${API}/agent/sessions/${path}`, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "The answer did not fit this question.";
    return { ok: false as const, body, text: JSON.stringify({ error: detail, status: response.status }) };
  }
  return { ok: true as const, body, text: JSON.stringify(body) };
}

const post = (body: object): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function Conversation({ sessionId }: { sessionId: string }) {
  const [state, setState] = useState<NextState | null>(null);
  const [learned, setLearned] = useState<Learned[]>([]);
  const [said, setSaid] = useState({ friend: "", you: "" });
  const [started, setStarted] = useState(false);
  const [past, setPast] = useState<Past[]>([]);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const revision = useRef<number | undefined>(undefined);
  const history = useRef<HTMLOListElement>(null);
  const [scroll, setScroll] = useState({ above: false, below: false });
  const [historyOpen, setHistoryOpen] = useState(false);

  const conversation = useConversation({
    // Expressive voices add tone tags like "[happy]"; they shape the audio but aren't for reading.
    // A new line from Forma replaces the bubble text and clears what the person said before it.
    onMessage: ({ message, source }) => setSaid(current => source === "user"
      ? { ...current, you: message } : { friend: message.replace(/\[[a-z ]{1,24}\]\s*/gi, ""), you: "" }),
    onError: message => setError(typeof message === "string" && /permission|notallowed/i.test(message)
      ? "Forma needs your microphone to listen. Allow the microphone in your browser (look for the icon next to the web address), then press Start talking again."
      : typeof message === "string" ? message : "The voice guide had a problem. Please try again."),
  });
  const live = conversation.status === "connected";

  function track(next: NextState) { revision.current = next.revision; setState(next); }

  // Earlier questions come from the saved session, so they survive a page refresh.
  async function loadPast() {
    try {
      const response = await fetch(`${API}/sessions/${sessionId}`);
      if (!response.ok) return;
      const session = await response.json();
      setPast(session.fields.filter((f: { status: string }) => f.status === "answered" || f.status === "skipped")
        .map((f: { field_id: string; simplified_question: string; original_question: string; user_response: string | null }) =>
          ({ id: f.field_id, question: f.simplified_question || f.original_question, answer: showAnswer(f.user_response) })));
    } catch { /* History is a convenience; the conversation still works without it. */ }
  }

  // Load the first question so it is visible before the conversation starts, and for the glossary.
  useEffect(() => {
    tool(`${sessionId}/next-question`).then(result => result.ok ? track(result.body) : setError(JSON.parse(result.text).error));
    tool(`${sessionId}/glossary`).then(result => { if (result.ok) setLearned(result.body.terms); });
    void loadPast();
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps
  // Keep the newest answer in view, and track whether there is more to scroll to in either direction.
  function measure() {
    const list = history.current;
    if (list) setScroll({ above: list.scrollTop > 4, below: list.scrollTop + list.clientHeight < list.scrollHeight - 4 });
  }
  function toLatest(smooth = false) {
    history.current?.scrollTo?.({ top: history.current.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }
  useEffect(() => { toLatest(); measure(); }, [past, historyOpen]);

  // Client tools: the browser binds the session and revision so the model never handles them.
  useConversationClientTool("get_next_question", async () => {
    const result = await tool(`${sessionId}/next-question`);
    if (result.ok) track(result.body);
    return result.text;
  });
  useConversationClientTool("save_answer", async (params: Record<string, unknown>) => {
    const raw = String(params.value_json ?? "");
    let value: unknown;
    try { value = JSON.parse(raw); } catch { value = raw; } // Unquoted free text is still text.
    const result = await tool(`${sessionId}/answers`, post({
      question_id: params.question_id, value, raw_response: String(params.raw_response ?? ""), revision: revision.current }));
    if (result.ok) { track(result.body.next); void loadPast(); }
    return result.text;
  });
  useConversationClientTool("skip_question", async (params: Record<string, unknown>) => {
    const result = await tool(`${sessionId}/skip`, post({ question_id: params.question_id, revision: revision.current }));
    if (result.ok) { track(result.body.next); void loadPast(); }
    return result.text;
  });
  useConversationClientTool("get_question_context", async (params: Record<string, unknown>) =>
    (await tool(`${sessionId}/questions/${encodeURIComponent(String(params.question_id))}/context`)).text);
  useConversationClientTool("explain_term", async (params: Record<string, unknown>) => {
    const entry = { term: String(params.term ?? "").trim(), explanation: String(params.explanation ?? "").trim(), example: String(params.example ?? "").trim() };
    const result = await tool(`${sessionId}/explain`, post({ question_id: params.question_id, ...entry }));
    if (result.ok) setLearned(current => [entry, ...current.filter(item => item.term.toLowerCase() !== entry.term.toLowerCase())]);
    return result.text;
  });

  async function start() {
    setStarting(true); setError("");
    try {
      const response = await fetch(`${API}/voice/agent-session`);
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw Error(typeof body.detail === "string" ? body.detail : "The voice guide could not start.");
      conversation.startSession({ signedUrl: body.signed_url, connectionType: "websocket" });
      setStarted(true);
    } catch (e) {
      setError(e instanceof TypeError ? "Can’t reach Forma. Make sure the backend is running on port 8000." : (e as Error).message);
    } finally { setStarting(false); }
  }

  function send(event: React.FormEvent) {
    event.preventDefault();
    if (!typed.trim() || !live) return;
    conversation.sendUserMessage(typed.trim());
    setTyped("");
  }

  const progress = state?.progress ?? {};
  const done = (progress.answered ?? 0) + (progress.skipped ?? 0);
  const total = done + (progress.unanswered ?? 0) + (progress.blocked ?? 0);
  const question = state?.question;
  const reference = question?.source_reference;
  const complete = state?.status === "complete";
  const connecting = starting || conversation.status === "connecting";
  const presence = connecting ? ["connecting", "Getting ready…"]
    : !live ? ["idle", started ? "Paused" : "Ready when you are"]
    : conversation.isSpeaking ? ["talking", "Forma is talking"]
    : conversation.isMuted ? ["muted", "Microphone is off"] : ["listening", "Listening to you"];

  function choose(option: string) {
    if (live) conversation.sendUserMessage(option);
  }

  return <section className="guide" aria-label="Talk with Forma">
    <div className="guide-heading">
      <div><p className="eyebrow">A FRIEND BY YOUR SIDE. ONE QUESTION AT A TIME.</p><h1>Let’s talk <span>it through.</span></h1></div>
      {complete && <Link className="button primary" href="/review" onClick={() => conversation.endSession()}>Review my answers <span>↗</span></Link>}
    </div>

    <div className="guide-progress">
      <div className="guide-progress-row">
        <strong>{complete ? "All questions done" : total ? `Question ${Math.min(done + 1, total)} of ${total}` : "Getting your questions…"}</strong>
        <span className={`guide-presence is-${presence[0]}`} role="status"><span aria-hidden="true" />{presence[1]}</span>
      </div>
      <div className="guide-bar" role="progressbar" aria-label="Questions done" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
        <span style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
      </div>
    </div>

    {past.length > 0 && <section className={`guide-history${historyOpen ? " is-open" : ""}${scroll.above ? " has-above" : ""}${scroll.below ? " has-below" : ""}`} aria-label="Earlier questions">
      <h2 className="guide-history-head">
        <button type="button" className="guide-history-toggle" aria-expanded={historyOpen} aria-controls="guide-history-list" onClick={() => setHistoryOpen(open => !open)}>
          <span className="guide-history-title">Earlier questions <span className="guide-history-count">{past.length}</span></span>
          {!historyOpen && <span className="guide-history-last">Last: {past[past.length - 1].answer ?? "Skipped"}</span>}
          <span className="guide-history-chevron" aria-hidden="true">▾</span>
        </button>
      </h2>
      {historyOpen && <>
      {scroll.above && <p className="guide-history-hint" aria-hidden="true">↑ Scroll up for earlier answers</p>}
      <ol id="guide-history-list" ref={history} tabIndex={0} aria-label={`${past.length} answered questions. Scroll to see them all.`} onScroll={measure}>
        {past.map((item, index) => <li key={item.id}>
          <span className="guide-history-num">{index + 1}</span>
          <div><p>{item.question}</p><strong>{item.answer ?? "Skipped"}</strong></div>
        </li>)}
      </ol>
      {scroll.below && <button type="button" className="guide-history-latest" onClick={() => toLatest(true)}>↓ Latest</button>}
      </>}
    </section>}

    <div className="guide-scene">
      <div className="guide-mascot"><Mascot talking={live && conversation.isSpeaking} /></div>
      <div className="guide-bubble">
        {said.friend && <p className="guide-says" aria-live="polite"><span>Forma</span>{said.friend}</p>}
        {question && state?.status === "question" && <>
          <div className="guide-card-meta"><span>Now answering</span>{reference?.section && <span>{reference.section}</span>}</div>
          <h2 aria-live="polite">{question.simplified_question}</h2>
          {question.options.length > 0 && <div className="guide-options" role="group" aria-label="Answer choices">
            {question.options.map(option => <button key={option} type="button" disabled={!live} onClick={() => choose(option)}>{option}</button>)}
          </div>}
          <details className="source-details" key={question.id}>
            <summary>ⓘ What the form says</summary>
            {reference?.page && <p><strong>From page {reference.page}</strong></p>}
            <blockquote>{question.original_text}</blockquote>
            {question.help_text && <p>{question.help_text}</p>}
          </details>
        </>}
        {complete && <><h2>You’re all done. Great work!</h2><p className="guide-lede">Look over your answers before you download your form.</p></>}
        {said.you && <p className="guide-heard"><span>You said</span>“{said.you}”</p>}
        {!live && !complete && <div className="guide-start">
          <button type="button" className="guide-start-button" disabled={connecting || !state} onClick={() => void start()}>
            <span aria-hidden="true">🎙</span>{connecting ? "Starting…" : started ? "Keep going" : "Start talking"}
          </button>
          <p>Forma will ask to use your microphone.<br />You can also type your answers. There’s no rush.</p>
        </div>}
        {live && <form className="guide-composer" onSubmit={send}>
          <label htmlFor="typed-answer" className="sr-only">Type your answer instead</label>
          <div className="guide-typed">
            <input id="typed-answer" value={typed} onChange={event => setTyped(event.target.value)} placeholder="Type your answer here, or just say it" autoComplete="off" />
            <button type="submit" className="button primary" disabled={!typed.trim()}>Send</button>
          </div>
          <div className="guide-controls">
            <button type="button" onClick={() => conversation.setMuted(!conversation.isMuted)}>{conversation.isMuted ? "🎙 Turn microphone on" : "🔇 Turn microphone off"}</button>
            <button type="button" onClick={() => conversation.endSession()}>⏸ Take a break</button>
          </div>
        </form>}
      </div>
    </div>

    {learned.length > 0 && <div className="guide-learned" aria-label="Words you learned">
      <h3>Words you learned</h3>
      {learned.map(item => <details key={item.term} open={item === learned[0]}>
        <summary>{item.term}</summary><p>{item.explanation}</p>{item.example && <p className="guide-example">For example: {item.example}</p>}
      </details>)}
    </div>}
    {error && <div className="error-message" role="alert">{error}</div>}
  </section>;
}

export default function GuidedConversation({ sessionId }: { sessionId: string }) {
  return <ConversationProvider><Conversation sessionId={sessionId} /></ConversationProvider>;
}
