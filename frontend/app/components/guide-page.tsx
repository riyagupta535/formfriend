"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import GuidedConversation from "./guided-conversation";
import Mascot from "./mascot";
import { Header, Footer, Steps } from "./shell";
import { startSampleSession } from "../../lib/sample-form";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function GuidePage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const key = sessionStorage.getItem("formfriend-session");
    if (!key) { setReady(true); return; }
    // Only agent sessions (created from generated questions) can be guided.
    fetch(`${API}/agent/sessions/${key}/next-question`).then(r => { if (r.ok) setSessionId(key); })
      .catch(() => setError("Can’t reach Forma. Make sure the backend is running on port 8000."))
      .finally(() => setReady(true));
  }, []);
  async function trySample() {
    setError("");
    try { setSessionId(await startSampleSession()); }
    catch (e) { setError(e instanceof TypeError ? "Can’t reach Forma. Make sure the backend is running on port 8000." : (e as Error).message); }
  }
  return <><Header compact /><main className="workflow guide-workflow"><Steps active={1} />
    {!ready ? <div className="empty-state" role="status">Finding your form…</div>
      : sessionId ? <GuidedConversation sessionId={sessionId} />
      : <div className="empty-state"><Mascot small /><h1>Let’s start with your form.</h1><p>Upload a document to talk it through, or try a short sample form.</p>
          <div className="guide-empty-actions"><Link className="button primary" href="/upload">Upload a form ↗</Link><button className="button secondary" onClick={() => void trySample()}>Try a sample form</button></div></div>}
    {error && <div className="error-message" role="alert">{error}</div>}
  </main><Footer /></>;
}
