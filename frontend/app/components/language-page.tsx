"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import QuestionLanguageSelect, { type QuestionLanguage } from "./question-language";
import { Header, Footer } from "./shell";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type PendingSession = { session_id: string; filename: string; language?: QuestionLanguage; agent_state?: object | null };

async function request(path: string, init?: RequestInit) {
  const response = await fetch(`${API}${path}`, init);
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(typeof result.detail === "string" ? result.detail : "Your form could not continue. Please try again.");
  return result;
}

export default function LanguagePage() {
  const router = useRouter();
  const [session, setSession] = useState<PendingSession | null>(null);
  const [language, setLanguage] = useState<QuestionLanguage>("en");
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const key = sessionStorage.getItem("formfriend-session");
    if (!key) { setReady(true); return; }
    let current = true;
    request(`/sessions/${key}`).then(next => {
      if (current) { setSession(next); setLanguage(next.language ?? "en"); }
    }).catch(reason => { if (current) setError(reason instanceof TypeError ? "Can’t reach forma. Make sure the backend is running on port 8000." : reason.message); })
      .finally(() => { if (current) setReady(true); });
    return () => { current = false; };
  }, []);

  async function continueToQuestions() {
    if (!session || busy) return;
    setBusy(true); setError("");
    try {
      const post = (body: object): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      await request(`/sessions/${session.session_id}/language`, post({ language }));
      const guided = session.agent_state ? session : await request("/agent/sessions/from-upload", post({ document_session_id: session.session_id }));
      sessionStorage.setItem("formfriend-session", guided.session_id);
      router.push("/guide");
    } catch (reason) {
      setError(reason instanceof TypeError ? "Can’t reach forma. Your upload is still here; please try again." : (reason as Error).message);
    } finally { setBusy(false); }
  }

  return <><Header /><main className="workflow">
    {!ready ? <div className="empty-state" role="status">Finding your form…</div>
      : !session ? <div className="empty-state"><h1>Let’s start with your form.</h1><p>Upload a document before choosing your question language.</p><Link className="button primary" href="/upload">Upload a form ↗</Link></div>
      : <section className="language-step" aria-labelledby="language-title">
        <h1 id="language-title">Which language would you like Fomi to use?</h1>
        <QuestionLanguageSelect value={language} onChange={setLanguage} disabled={busy} />
        <button type="button" className="button primary" disabled={busy} onClick={() => void continueToQuestions()}>{busy ? "Preparing your questions…" : "Continue to questions"}<span aria-hidden="true">→</span></button>
      </section>}
    {error && <p className="error-message" role="alert">{error}</p>}
  </main><Footer /></>;
}
