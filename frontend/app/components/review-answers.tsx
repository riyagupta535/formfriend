"use client";
import Link from "next/link";
import { useState } from "react";
import AnswerInput, { type AnswerField } from "./answer-input";
import Mascot from "./mascot";

type ReviewField = AnswerField & {
  field_id: string; original_question: string; simplified_question: string;
  source_page: number; user_response: string | null;
};
type ReviewSession = {
  session_id: string; filename: string; document_type?: string;
  pdf_has_answer_sheet?: boolean; fields: ReviewField[];
};
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function ReviewAnswers({ session, onClear }: {session: ReviewSession; onClear: () => void}) {
  const [values, setValues] = useState(() => Object.fromEntries(session.fields.map(f => [f.field_id, f.user_response || ""])));
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [downloaded, setDownloaded] = useState(false);
  const missing = session.fields.filter(f => !values[f.field_id]?.trim()).length;
  const filledPdf = !session.document_type || session.document_type === "pdf";
  function edit(id: string, value: string) {
    setValues(current => ({...current, [id]: value}));
    setReviewed(false); setDownloaded(false); setError("");
  }
  async function download() {
    if (!reviewed || busy) return;
    setBusy(true); setError(""); setDownloaded(false);
    try {
      const response = await fetch(`${API}/sessions/${session.session_id}/review/export`, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({reviewed: true, answers: session.fields.map(f => ({field_id: f.field_id, value: values[f.field_id]}))}),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw Error(typeof result.detail === "string" ? result.detail : "Your PDF could not be created. Please try again.");
      }
      const blob = await response.blob();
      if (!blob.type.startsWith("application/pdf")) throw Error("The server did not return a PDF. Please try again.");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const stem = session.filename.replace(/\.[^.]+$/, "");
      link.download = `formfriend-${stem}${filledPdf ? "" : "-answers"}.pdf`;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setDownloaded(true);
    } catch (e) {
      setError(e instanceof TypeError ? "Cannot reach FormFriend. Your edits are still here. Check the backend and try again." : (e as Error).message);
    } finally { setBusy(false); }
  }
  return <>
    <div className="page-intro"><p className="eyebrow">ONE LAST LOOK, AT YOUR PACE</p><h1>Your answers.<br/><span>Ready when you are.</span></h1><p>Read through everything and make any changes before downloading your PDF.</p></div>
    <div className="review-layout">
      <section className="review-card" aria-label="Review all answers" aria-busy={busy}>
        <div className="review-title"><h2>Your answers</h2><span>{session.fields.length - missing} / {session.fields.length} answered</span></div>
        {session.fields.map((field, index) => <div className="review-field" key={field.field_id}>
          <label id={`review-${index}-label`} htmlFor={`review-${index}`}><span>{String(index + 1).padStart(2, "0")}</span>{field.original_question}</label>
          {field.simplified_question && field.simplified_question !== field.original_question && <p className="review-simple">{field.simplified_question}</p>}
          <AnswerInput id={`review-${index}`} field={field} value={values[field.field_id]} onChange={value => edit(field.field_id, value)} disabled={busy}/>
          <small>{!values[field.field_id]?.trim() ? "No answer provided · " : ""}{field.source_page > 0 ? `${session.document_type === "image" ? "Screenshot" : "Source page"} ${field.source_page}` : "Source page not provided"}</small>
        </div>)}
      </section>
      <aside className="download-card"><Mascot small/><h3>Looking good, friend.</h3>
        <p>{!filledPdf ? "Your PDF will be an answer sheet to use alongside your original document. The original document will not be filled." : session.pdf_has_answer_sheet ? "Your original PDF will include filled fields where supported, plus an answer sheet for printed or scanned questions." : "Your answers will be placed in your original PDF’s fillable fields."}</p>
        <div className="document-pill">▤ <span>{session.filename}</span></div>
        {missing > 0 && <p className="review-missing" role="status">{missing} {missing === 1 ? "answer is" : "answers are"} still blank. You can add them now or leave them blank in the PDF.</p>}
        <label className="review-confirm"><input type="checkbox" checked={reviewed} disabled={busy} onChange={event => {setReviewed(event.target.checked); setDownloaded(false);}}/><span>I’ve reviewed my answers and want to export this PDF.</span></label>
        <p className="review-save-note">Your edits are saved together when you export. Exporting does not submit your form.</p>
        <button className="button primary" disabled={busy || !reviewed} onClick={() => void download()}>{busy ? "Creating your PDF…" : "Download PDF"}<span aria-hidden="true">↓</span></button>
        {downloaded && <p className="success-message" role="status">✓ Your PDF download has started.</p>}
        {error && <p className="error-message" role="alert">{error}</p>}
        <Link className="text-button" href="/guide" onClick={event => {if (busy) event.preventDefault();}}>← Back to guided questions</Link>
        <button className="text-button" disabled={busy} onClick={onClear}>Clear session & start fresh</button>
      </aside>
    </div>
  </>;
}
