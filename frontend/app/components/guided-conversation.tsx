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
type Line = { id: number; speaker: "friend" | "you"; text: string };

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
  const [lines, setLines] = useState<Line[]>([]);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const revision = useRef<number | undefined>(undefined);
  const lineId = useRef(0);
  const transcript = useRef<HTMLDivElement>(null);

  const conversation = useConversation({
    // Expressive voices add tone tags like "[happy]"; they shape the audio but aren't for reading.
    onMessage: ({ message, source }) => setLines(current => [...current, { id: ++lineId.current, speaker: source === "user" ? "you" : "friend",
      text: source === "user" ? message : message.replace(/\[[a-z ]{1,24}\]\s*/gi, "") }]),
    onError: message => setError(typeof message === "string" && /permission|notallowed/i.test(message)
      ? "Form Friend needs your microphone to listen. Allow the microphone in your browser (look for the icon next to the web address), then press Start talking again."
      : typeof message === "string" ? message : "The voice guide had a problem. Please try again."),
  });
  const live = conversation.status === "connected";

  function track(next: NextState) { revision.current = next.revision; setState(next); }

  // Load the first question so it is visible before the conversation starts, and for the glossary.
  useEffect(() => {
    tool(`${sessionId}/next-question`).then(result => result.ok ? track(result.body) : setError(JSON.parse(result.text).error));
    tool(`${sessionId}/glossary`).then(result => { if (result.ok) setLearned(result.body.terms); });
  }, [sessionId]);
  useEffect(() => { transcript.current?.scrollTo?.({ top: transcript.current.scrollHeight }); }, [lines]);

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
    if (result.ok) track(result.body.next);
    return result.text;
  });
  useConversationClientTool("skip_question", async (params: Record<string, unknown>) => {
    const result = await tool(`${sessionId}/skip`, post({ question_id: params.question_id, revision: revision.current }));
    if (result.ok) track(result.body.next);
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
    } catch (e) {
      setError(e instanceof TypeError ? "Can’t reach Form Friend. Make sure the backend is running on port 8000." : (e as Error).message);
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

  return <section className="chat-workspace guide" aria-label="Talk with Form Friend">
    <div className="chat-heading">
      <div><p className="eyebrow">A FRIEND BY YOUR SIDE. ONE QUESTION AT A TIME.</p><h1>Let’s talk <span>it through.</span></h1></div>
      {state?.status === "complete" && <Link className="button primary" href="/review" onClick={() => conversation.endSession()}>Review my answers <span>↗</span></Link>}
    </div>
    <div className="chat-panel">
      <div className="chat-toolbar"><span>{live ? (conversation.isSpeaking ? "Form Friend is talking" : "Listening to you") : "Not started"}</span><span>{done} of {total} done</span></div>
      <progress value={done} max={Math.max(total, 1)} aria-label="Questions done" />
      <div className="guide-body">
        <div className="guide-main">
          {question && state?.status === "question" && <div className="chat-message chat-friend-current">
            <div className="chat-message-meta"><span className="chat-speaker">Now answering</span>{reference?.section && <span>{reference.section.toUpperCase()}</span>}</div>
            <h2 aria-live="polite">{question.simplified_question}</h2>
            {question.options.length > 0 && <ul className="guide-options">{question.options.map(option => <li key={option}>{option}</li>)}</ul>}
            <details className="source-details" key={question.id}>
              <summary>ⓘ What the form says</summary>
              {reference?.page && <p><strong>From page {reference.page}</strong></p>}
              <blockquote>{question.original_text}</blockquote>
              {question.help_text && <p>{question.help_text}</p>}
            </details>
          </div>}
          {state?.status === "complete" && <div className="chat-message chat-friend-current"><h2>You’re all done. Great work!</h2><p>Look over your answers before you download your form.</p></div>}
          <div className="guide-transcript" ref={transcript} aria-label="Conversation so far" aria-live="polite">
            {lines.length === 0 && <p className="chat-welcome">Press “Start talking” and Form Friend will ask you one small question at a time.<br />You can speak or type. There’s no rush.</p>}
            {lines.map(line => <div key={line.id} className={`chat-message ${line.speaker === "you" ? "chat-user" : "chat-friend-history"}`}>
              <span className="chat-speaker">{line.speaker === "you" ? "You" : "Form Friend"}</span><p>{line.text}</p></div>)}
          </div>
        </div>
        <aside className="guide-side">
          <Mascot talking={live && conversation.isSpeaking} />
          {learned.length > 0 && <div className="guide-learned" aria-label="Words you learned">
            <h3>Words you learned</h3>
            {learned.map(item => <details key={item.term} open={item === learned[0]}>
              <summary>{item.term}</summary><p>{item.explanation}</p>{item.example && <p className="guide-example">For example: {item.example}</p>}
            </details>)}
          </div>}
        </aside>
      </div>
      <form className="chat-composer" onSubmit={send}>
        {!live ? <div className="chat-send-row">
          <span className="chat-composer-note">Form Friend will ask to use your microphone.</span>
          <button type="button" className="button primary" disabled={starting || !state || conversation.status === "connecting"} onClick={() => void start()}>
            {starting || conversation.status === "connecting" ? "Starting…" : lines.length ? "Keep going" : "Start talking"}<span aria-hidden="true">●</span></button>
        </div> : <>
          <label htmlFor="typed-answer" className="sr-only">Type your answer instead</label>
          <div className="guide-typed">
            <input id="typed-answer" value={typed} onChange={event => setTyped(event.target.value)} placeholder="Or type your answer here" autoComplete="off" />
            <button type="submit" className="button secondary" disabled={!typed.trim()}>Send</button>
          </div>
          <div className="chat-send-row">
            <button type="button" className="chat-back" onClick={() => conversation.setMuted(!conversation.isMuted)}>{conversation.isMuted ? "Turn microphone on" : "Turn microphone off"}</button>
            <button type="button" className="button secondary" onClick={() => conversation.endSession()}>Take a break</button>
          </div>
        </>}
      </form>
    </div>
    {error && <div className="error-message" role="alert">{error}</div>}
  </section>;
}

export default function GuidedConversation({ sessionId }: { sessionId: string }) {
  return <ConversationProvider><Conversation sessionId={sessionId} /></ConversationProvider>;
}
