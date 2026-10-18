"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import Mascot from "./mascot";
import { type AnswerField } from "./answer-input";
import ReviewAnswers from "./review-answers";
import { Header, Footer, Steps } from "./shell";
type Field = AnswerField & { field_id:string; original_question:string; simplified_question:string; source_page:number; source_kind?:"fillable"|"text-layer"|"ocr"; user_response:string|null; confirmed:boolean };
type Session = { session_id:string; filename:string; mode:string; fields:Field[]; warnings:string[]; document_type?:string; pdf_has_answer_sheet?:boolean };
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
async function request(path:string, options?:RequestInit) { const response=await fetch(`${API}${path}`,options);if(!response.ok){const result=await response.json().catch(()=>({}));throw Error(typeof result.detail==="string"?result.detail:"Something went wrong. Please try again.");}return response.json(); }
export default function Workflow({ stage }: { stage:"upload"|"review" }) {
 const router=useRouter();const [session,setSession]=useState<Session|null>(null);const [ready,setReady]=useState(false);const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [drag,setDrag]=useState(false);const fileInput=useRef<HTMLInputElement>(null);
 const busyMessage="Getting to know your form…";
 const remember=useCallback((next:Session)=>{setSession(next);sessionStorage.setItem("formfriend-session",next.session_id);},[]);
 useEffect(()=>{const key=sessionStorage.getItem("formfriend-session");if(key){request(`/sessions/${key}`).then(remember).catch(e=>{sessionStorage.removeItem("formfriend-session");setError(e instanceof TypeError?"Can’t reach forma. Start the backend and try again.":e.message);}).finally(()=>setReady(true));}else setReady(true);},[remember]);
 async function upload(selection:File[]|FileList){setError("");const files=Array.from(selection);if(!files.length)return;if(files.length>10){setError("Choose no more than 10 screenshots.");return;}if(files.some(file=>file.size>10*1024*1024)){setError("Each file must be smaller than 10 MB.");return;}if(files.reduce((total,file)=>total+file.size,0)>30*1024*1024){setError("The combined screenshots must be smaller than 30 MB.");return;}if(files.some(file=>!/\.(pdf|docx|png|jpe?g)$/i.test(file.name))){setError("Choose a PDF, DOCX, PNG, or JPG file.");return;}if(files.length>1&&files.some(file=>!/\.(png|jpe?g)$/i.test(file.name))){setError("Choose one PDF or DOCX, or up to 10 PNG/JPG screenshots.");return;}setBusy(true);const controller=new AbortController();const uploadTimeout=setTimeout(()=>controller.abort(),120000);try{const body=new FormData();for(const file of files)body.append(files.length===1?"file":"files",file);const uploaded=await request("/sessions",{method:"POST",body,signal:controller.signal});const guided=await request("/agent/sessions/from-upload",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({document_session_id:uploaded.session_id}),signal:controller.signal});if(session)await request(`/sessions/${session.session_id}`,{method:"DELETE"}).catch(()=>{});remember(await request(`/sessions/${guided.session_id}`));router.push("/guide");}catch(e){setError(e instanceof Error&&e.name==="AbortError"?"This upload took too long. Please try again, or use a smaller PDF to test.":e instanceof TypeError?"Can’t reach forma. Make sure the backend is running on port 8000.":(e as Error).message);}finally{clearTimeout(uploadTimeout);setBusy(false);if(fileInput.current)fileInput.current.value="";}}
 async function clear(){if(!session)return;setBusy(true);try{await request(`/sessions/${session.session_id}`,{method:"DELETE"});sessionStorage.removeItem("formfriend-session");setSession(null);router.push("/upload");}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <><Header/><main className={stage==="review"?"workflow review-workflow":"workflow"}><Steps active={stage==="upload"?0:2}/>{stage==="upload"?<section className="upload-a" aria-labelledby="upload-title">
  <div className="upload-a-intro"><h1 id="upload-title">Upload your form</h1><p>We’ll turn it into simple questions, one at a time.</p></div>
  <div className={`upload-a-stage ${drag?"is-dragging":""}`}>
    <div className="upload-a-mascot" aria-hidden="true"><Mascot/></div>
    <p className="upload-a-greeting">We’ve got this.</p>
  <div className={`upload-a-box ${drag?"is-dragging":""}`} aria-busy={busy} onDragOver={e=>{e.preventDefault();setDrag(true);}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);if(e.dataTransfer.files.length&&!busy)void upload(e.dataTransfer.files);}}>
    {busy?<><h2>Reading your form…</h2><p className="upload-a-hint" role="status">Finding the questions and making them simpler. This can take a minute.</p></>
      :<><h2><span className="upload-a-drag">Drag your file here, or</span><span className="upload-a-tap">Add your form</span></h2>
        <input ref={fileInput} id="document" className="sr-only" type="file" accept=".pdf,.docx,.png,.jpg,.jpeg" multiple disabled={busy} onChange={e=>{if(e.target.files?.length)void upload(e.target.files);}}/>
        <button className="button primary upload-a-button" onClick={()=>fileInput.current?.click()}>Choose a file</button>
        <p className="upload-a-hint">PDF, Word, or photos of the form. Several photos? Select them together, in page order.</p></>}
  </div>
  </div>
  {session&&<Link className="upload-a-resume" href="/guide">Continue where you left off →</Link>}
  <ul className="upload-a-points">
    <li><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>Deleted after an hour</li>
    <li><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>Talk or type your answers</li>
    <li><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4"/></svg>Review before you download</li>
  </ul>
</section>:!ready?<div className="empty-state" role="status">Finding your form…</div>:!session?<div className="empty-state"><Mascot small/><h1>Let’s start with your form.</h1><p>Upload a document to begin your guided questions.</p><Link className="button primary" href="/upload">Upload a form ↗</Link></div>:<ReviewAnswers key={session.session_id} session={session} onClear={()=>void clear()}/>}{error&&<div className="error-message" role="alert">{error}</div>}{session&&stage!=="upload"&&session.warnings.map(w=><p className="workflow-warning" key={w}>{w}</p>)}</main><Footer/></>;
}
