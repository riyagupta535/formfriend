"use client";
import { useEffect, useRef, useState } from "react";
import Mascot from "./mascot";
import AnswerInput, { selectedOptions, type AnswerField } from "./answer-input";
import VoiceControls from "../../components/VoiceControls";

type ChatField = AnswerField & {
  field_id: string;
  original_question: string;
  simplified_question: string;
  source_page: number;
  user_response: string | null;
};
type Props = {
  session: { session_id: string; filename: string; document_type?: string; mode: string; fields: ChatField[] };
  index: number;
  value: string;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onNavigate: (index: number) => void;
  onReview: () => void;
};
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function displayAnswer(field: ChatField) {
  if (!field.user_response?.trim()) return "Skipped for now";
  return field.answer_type === "multichoice"
    ? selectedOptions(field.user_response).join(", ")
    : field.user_response;
}

export default function QuestionChat({ session, index, value, busy, onChange, onSubmit, onNavigate, onReview }: Props) {
  const [speaking, setSpeaking] = useState(false);
  const [mouthOpen, setMouthOpen] = useState(0);
  const activeMessage = useRef<HTMLDivElement>(null);
  const field = session.fields[index];
  const answered = session.fields.filter(item => item.user_response?.trim()).length;
  useEffect(() => {
    activeMessage.current?.scrollIntoView?.({ behavior: "instant", block: "nearest" });
  }, [index]);
  if (!field) return null;

  return <section className="chat-workspace" aria-label="Conversation with Form Friend">
    <div className="chat-heading">
      <div><p className="eyebrow">A FRIEND BY YOUR SIDE. ONE QUESTION AT A TIME.</p><h1>Let’s talk <span>it through.</span></h1></div>
      <button className="button secondary" disabled={busy} onClick={onReview}>Review my answers <span>↗</span></button>
    </div>
    <div className="chat-panel">
      <div className="chat-toolbar">
        <div className="chat-document"><span aria-hidden="true">▤</span><span>{session.filename}</span></div>
        <span>{answered} of {session.fields.length} answered</span>
      </div>
      <progress value={answered} max={session.fields.length} aria-label="Questions answered" />
      <div className="chat-scroll" aria-label="Conversation history">
        <p className="chat-welcome">Hi, I’m your Form Friend. We’ll work through this together.<br />You can type, speak, or take a moment. There’s no rush.</p>
        {session.fields.slice(0, index).map((previous, i) => <div className="chat-exchange" key={previous.field_id}>
          <div className="chat-message chat-friend-history"><span className="chat-speaker">Form Friend</span><p>{previous.simplified_question}</p></div>
          <div className="chat-message chat-user"><span className="chat-speaker">You</span><p>{displayAnswer(previous)}</p><button disabled={busy} onClick={() => onNavigate(i)}>Edit answer</button></div>
        </div>)}
        <div className="chat-current" ref={activeMessage}>
          <div className="chat-question">
            <div className="chat-message chat-friend-current">
              <div className="chat-message-meta"><span className="chat-speaker">Form Friend</span><span>QUESTION {index + 1} OF {session.fields.length}</span></div>
              {index > 0 && <p className="chat-acknowledgement">{session.fields[index - 1].user_response?.trim() ? "Got it, I’ve saved your answer. Here’s the next one." : "We can come back to that one. Let’s try this."}</p>}
              <h2 aria-live="polite">{field.simplified_question}</h2>
              <details className="source-details" key={field.field_id}>
                <summary>ⓘ See more details</summary>
                <p><strong>From page {field.source_page}</strong></p>
                <blockquote>{field.original_question}</blockquote>
                <p>This is the wording from your form. Check it before answering.</p>
                {(!session.document_type || session.document_type === "pdf") && <img className="source-preview" loading="lazy"
                  src={`${API}/sessions/${session.session_id}/fields/${encodeURIComponent(field.field_id)}/source`}
                  alt={`Page ${field.source_page} of your form, with this field outlined in teal`} />}
              </details>
            </div>
          </div>
          <aside className="chat-mascot" aria-label="Your Form Friend companion">
            <Mascot talking={speaking} mouthOpen={mouthOpen} />
            <div className={`chat-presence ${speaking ? "is-speaking" : ""}`}><span aria-hidden="true">●</span>{speaking ? "Talking to you…" : "I’m here for you"}</div>
          </aside>
        </div>
      </div>
      <form className="chat-composer" aria-busy={busy} onSubmit={event => { event.preventDefault(); onSubmit(); }}>
        <div className="chat-composer-heading"><label id="answer-label" htmlFor="answer">Your answer</label><span>{field.answer_type && !["text", "number"].includes(field.answer_type) ? "Choose an option below" : "Type it or say it. Your choice."}</span></div>
        <AnswerInput id="answer" field={field} value={value} onChange={onChange} disabled={busy} />
        <VoiceControls fieldId={field.field_id} question={field.simplified_question} answer={value} onAnswer={onChange}
          showAvatar={false} onMouthChange={setMouthOpen} disabled={busy} allowDictation={!field.answer_type || ["text", "number"].includes(field.answer_type)} autoPlay onSpeakingChange={setSpeaking} />
        <div className="chat-send-row">
          <button type="button" className="chat-back" disabled={busy || index === 0} onClick={() => onNavigate(index - 1)}>← Previous question</button>
          <button type="submit" className="button primary" disabled={busy}>
            {busy ? "Saving…" : index === session.fields.length - 1 ? "Send & review" : value.trim() ? "Send answer" : "Skip for now"}<span aria-hidden="true">↑</span>
          </button>
        </div>
        <p className="chat-composer-note">Your answer is saved when you send it. You can edit it later.</p>
      </form>
    </div>
    <p className="chat-session-note">{session.mode === "mock" ? "Using the original form questions. AI simplification will be added later." : "Questions simplified with Step 5 Preview."}</p>
  </section>;
}
