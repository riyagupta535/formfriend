"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import Mascot from "./mascot";
import { chooseDecisionAnswer, currentDecisionNode, type DecisionStep, type DecisionTree } from "./decision-tree";
import { Header, Footer, Steps } from "./shell";
import GuidedCalculation, { type CalculationSpec, type GuidedQuestion } from "./guided-calculation";
import WorksheetWorkflow, { type WorksheetSpec } from "./worksheet-workflow";
import EligibilityWorkflow, { type EligibilityWorkflowSpec } from "./eligibility-workflow";
import TableLookupWorkflow, { type TableLookupSpec } from "./table-lookup-workflow";
import PayPeriodCalculation, { type PayPeriodCalculationSpec } from "./pay-period-calculation";
type Field = { field_id:string; original_question:string; simplified_question:string; helper_text?:string|null; subquestions?:GuidedQuestion[]; calculation?:CalculationSpec|null; decision_tree?:DecisionTree|null; worksheet?:WorksheetSpec|null; eligibility_workflow?:EligibilityWorkflowSpec|null; table_lookup?:TableLookupSpec|null; pay_period_calculation?:PayPeriodCalculationSpec|null; simplification_status?:"pending"|"complete"|"failed"; simplification_confidence?:"high"|"medium"|"low"; answer_type?:string; options?:string[]; source_page:number; source_kind?:"fillable"|"text-layer"|"ocr"; user_response:string|null; confirmed:boolean };
type Session = { session_id:string; filename:string; mode:string; simplification_status?:"pending"|"running"|"complete"|"partial"; fields:Field[]; warnings:string[]; document_type?:string };
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
async function request(path:string, options?:RequestInit) { const response=await fetch(`${API}${path}`,options);if(!response.ok){const result=await response.json().catch(()=>({}));throw Error(typeof result.detail==="string"?result.detail:"Something went wrong. Please try again.");}return response.json(); }
type Recognition = { lang:string; interimResults:boolean; onresult:((e:{results:{transcript:string}[][]})=>void)|null; onerror:(()=>void)|null; onend:(()=>void)|null; start:()=>void; stop:()=>void };
export default function Workflow({ stage }: { stage:"upload"|"questions"|"review" }) {
 const router=useRouter();const [session,setSession]=useState<Session|null>(null);const [ready,setReady]=useState(false);const [index,setIndex]=useState(0);const [value,setValue]=useState("");const [decisionPath,setDecisionPath]=useState<DecisionStep[]>([]);const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [drag,setDrag]=useState(false);const [muted,setMuted]=useState(false);const [speaking,setSpeaking]=useState(false);const [listening,setListening]=useState(false);const [notice,setNotice]=useState("");const [downloaded,setDownloaded]=useState(false);const fileInput=useRef<HTMLInputElement>(null);const recognition=useRef<Recognition|null>(null);const audio=useRef<HTMLAudioElement|null>(null);const readVersion=useRef(0);const autoReadKey=useRef("");const audioUrl=useRef<string|null>(null);const field=session?.fields[index];const simplifying=session?.simplification_status==="pending"||session?.simplification_status==="running";const fieldLoading=field?.simplification_status==="pending";const fieldFailed=field?.simplification_status==="failed";const decisionComplete=!!(field?.decision_tree&&value&&field.options?.includes(value));const decisionNode=field?.decision_tree&&!decisionComplete?currentDecisionNode(field.decision_tree,decisionPath):null;const answerSheet=session?.document_type==="image"||(session?.document_type==="pdf"&&session.fields.some(item=>item.source_kind&&item.source_kind!=="fillable"));
 const remember=useCallback((next:Session)=>{setSession(next);sessionStorage.setItem("formfriend-session",next.session_id);},[]);
 useEffect(()=>{const key=sessionStorage.getItem("formfriend-session");setMuted(localStorage.getItem("formfriend-muted")==="true");if(key){request(`/sessions/${key}`).then(data=>{remember(data);setValue(data.fields[0]?.user_response||"");}).catch(e=>{sessionStorage.removeItem("formfriend-session");setError(e instanceof TypeError?"Can’t reach Form Friend. Start the backend and try again.":e.message);}).finally(()=>setReady(true));}else setReady(true);},[remember]);
 useEffect(()=>{if(!session||!(["pending","running"] as const).includes(session.simplification_status as "pending"|"running"))return;let stopped=false;const poll=async()=>{try{const next:Session=await request(`/sessions/${session.session_id}`);if(stopped)return;const changed=next.simplification_status!==session.simplification_status||next.fields.some((item,i)=>item.simplification_status!==session.fields[i]?.simplification_status||item.simplified_question!==session.fields[i]?.simplified_question||item.helper_text!==session.fields[i]?.helper_text||JSON.stringify(item.subquestions||[])!==JSON.stringify(session.fields[i]?.subquestions||[])||JSON.stringify(item.decision_tree||null)!==JSON.stringify(session.fields[i]?.decision_tree||null)||JSON.stringify(item.calculation||null)!==JSON.stringify(session.fields[i]?.calculation||null));if(changed)remember(next);}catch{/* Keep the current extracted questions if a background poll fails. */}};void poll();const timer=window.setInterval(()=>void poll(),2000);return()=>{stopped=true;window.clearInterval(timer);};},[session,remember]);
 const stopSpeech=useCallback(()=>{readVersion.current++;audio.current?.pause();audio.current=null;if(audioUrl.current){URL.revokeObjectURL(audioUrl.current);audioUrl.current=null;}window.speechSynthesis?.cancel();setSpeaking(false);},[]);
 const read=useCallback(async()=>{
  stopSpeech();if(!field||!session||muted)return;const version=readVersion.current;
  try{const nodeQuery=decisionNode?`?node_id=${encodeURIComponent(decisionNode.node_id)}`:"";const response=await fetch(`${API}/sessions/${session.session_id}/fields/${encodeURIComponent(field.field_id)}/speech${nodeQuery}`);if(response.ok){const blob=await response.blob();if(version!==readVersion.current)return;const url=URL.createObjectURL(blob);audioUrl.current=url;const player=new Audio(url);audio.current=player;const release=()=>{URL.revokeObjectURL(url);setSpeaking(false);};player.onended=release;player.onerror=release;try{await player.play();setSpeaking(true);return;}catch{release();setNotice("Press Read this question to enable audio in your browser.");}}}catch{/* Use built-in speech when the provider is unavailable. */}
  if(version!==readVersion.current||!("speechSynthesis" in window))return;
 const speech=new SpeechSynthesisUtterance(decisionNode?.question||field.simplified_question);speech.rate=.9;speech.onstart=()=>setSpeaking(true);speech.onend=()=>setSpeaking(false);speech.onerror=()=>setSpeaking(false);window.speechSynthesis.speak(speech);
 },[decisionNode,field,session,muted,stopSpeech]);
 async function readEligibility(step:string,fallbackText:string){
  stopSpeech();if(!field||!session||muted)return;const version=readVersion.current;
  try{const response=await fetch(`${API}/sessions/${session.session_id}/fields/${encodeURIComponent(field.field_id)}/speech?eligibility_step=${encodeURIComponent(step)}`);if(response.ok){const blob=await response.blob();if(version!==readVersion.current)return;const url=URL.createObjectURL(blob);audioUrl.current=url;const player=new Audio(url);audio.current=player;const release=()=>{URL.revokeObjectURL(url);setSpeaking(false);};player.onended=release;player.onerror=release;await player.play();setSpeaking(true);return;}}catch{/* Use browser speech below. */}
  if(version!==readVersion.current||!("speechSynthesis" in window))return;const speech=new SpeechSynthesisUtterance(fallbackText);speech.rate=.9;speech.onstart=()=>setSpeaking(true);speech.onend=()=>setSpeaking(false);speech.onerror=()=>setSpeaking(false);window.speechSynthesis.speak(speech);
 }
 useEffect(()=>{const spokenQuestion=decisionNode?.question||field?.simplified_question;const key=stage==="questions"&&!fieldLoading&&!fieldFailed&&field?`${field.field_id}:${decisionNode?.node_id||"field"}:${spokenQuestion}`:"";if(key&&key!==autoReadKey.current){autoReadKey.current=key;void read();}return stopSpeech;},[decisionNode,field,fieldFailed,fieldLoading,read,stage,stopSpeech]);
 useEffect(()=>()=>recognition.current?.stop(),[]);
 async function upload(selection:File[]|FileList){setError("");const files=Array.from(selection);if(!files.length)return;if(files.length>10){setError("Choose no more than 10 screenshots.");return;}if(files.some(file=>file.size>10*1024*1024)){setError("Each file must be smaller than 10 MB.");return;}if(files.reduce((total,file)=>total+file.size,0)>30*1024*1024){setError("The combined screenshots must be smaller than 30 MB.");return;}if(files.some(file=>!/\.(pdf|docx|png|jpe?g)$/i.test(file.name))){setError("Choose a PDF, DOCX, PNG, or JPG file.");return;}if(files.length>1&&files.some(file=>!/\.(png|jpe?g)$/i.test(file.name))){setError("Choose one PDF or DOCX, or up to 10 PNG/JPG screenshots.");return;}setBusy(true);try{const body=new FormData();for(const file of files)body.append(files.length===1?"file":"files",file);const next=await request("/sessions",{method:"POST",body});if(session)await request(`/sessions/${session.session_id}`,{method:"DELETE"}).catch(()=>{});remember(next);router.push("/questions");}catch(e){setError(e instanceof TypeError?"Can’t reach Form Friend. Make sure the backend is running on port 8000.":(e as Error).message);}finally{setBusy(false);if(fileInput.current)fileInput.current.value="";}}
 async function saveField(f:Field,answer:string){return request(`/sessions/${session!.session_id}/fields/${encodeURIComponent(f.field_id)}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({value:answer,confirmed:!!answer.trim()})});}
 async function next(answer=value){if(!field||!session)return;recognition.current?.stop();setBusy(true);setError("");try{remember(await saveField(field,answer));setDecisionPath([]);if(index===session.fields.length-1)router.push("/review");else{setIndex(index+1);setValue(session.fields[index+1].user_response||"");}}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 function chooseBranch(label:string){if(!field?.decision_tree)return;try{const result=chooseDecisionAnswer(field.decision_tree,decisionPath,label);setDecisionPath(result.path);if(result.terminalOption){setValue(result.terminalOption);void next(result.terminalOption);}}catch(e){setError((e as Error).message);}}
 function listen(){const w=window as unknown as {SpeechRecognition?:new()=>Recognition;webkitSpeechRecognition?:new()=>Recognition};const Constructor=w.SpeechRecognition||w.webkitSpeechRecognition;if(!Constructor){setNotice("Voice input isn’t available in this browser. You can type your answer below.");return;}if(listening){recognition.current?.stop();return;}const r=new Constructor();r.lang="en-US";r.interimResults=false;r.onresult=e=>setValue(previous=>[previous,e.results[0][0].transcript].filter(Boolean).join(" "));r.onerror=()=>{setListening(false);setNotice("Couldn’t use your microphone. Check browser permissions or type your answer.");};r.onend=()=>setListening(false);recognition.current=r;stopSpeech();try{r.start();setListening(true);}catch{setNotice("Microphone could not start. Please try again.");}}
 async function download(){if(!session)return;setBusy(true);setError("");try{let latest=session;for(const f of session.fields)latest=await saveField(f,f.user_response||"");remember(latest);const response=await fetch(`${API}/sessions/${session.session_id}/export`);if(!response.ok){const result=await response.json();throw Error(result.detail||"Download failed.");}const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=answerSheet?"formfriend-answers.txt":`formfriend-${session.filename}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);setDownloaded(true);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function clear(){if(!session)return;setBusy(true);try{await request(`/sessions/${session.session_id}`,{method:"DELETE"});sessionStorage.removeItem("formfriend-session");setSession(null);router.push("/upload");}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <>
<Header/>
<main className="workflow">
<Steps active={stage==="upload"?0:stage==="questions"?1:2}/>{stage==="upload"?<>
<div className="page-intro">
<p className="eyebrow">LET’S START WITH ONE SMALL STEP</p>
<h1>Bring your form.<br/>
<span>We’ll bring the help.</span>
</h1>
<p>A few questions, a little guidance, and a friend by your side.</p>
</div>
<div className="upload-layout">
<section className={`upload-card ${drag?"dragging":""}`} aria-busy={busy} onDragOver={e=>{e.preventDefault();setDrag(true);}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);if(e.dataTransfer.files.length&&!busy)void upload(e.dataTransfer.files);}}>
<div className="upload-symbol">↥</div>
<h2>{busy?"Getting to know your form…":"Drop your form right here"}</h2>
<p>{busy?"Finding the fields and making the questions a little simpler.":"Choose one document, or several screenshots of the same form."}</p>
<input ref={fileInput} id="document" className="sr-only" type="file" accept=".pdf,.docx,.png,.jpg,.jpeg" multiple disabled={busy} onChange={e=>{if(e.target.files?.length)void upload(e.target.files);}}/>
<button className="button primary" disabled={busy} onClick={()=>fileInput.current?.click()}>{busy?"Working on it…":"Choose your form"}<span>＋</span>
</button>
<div className="file-types">
<span>PDF</span>
<span>DOCX</span>
<span>PNG / JPG</span>
</div>
<small>One PDF/DOCX, or up to 10 screenshots · 30 MB combined</small>
</section>
<aside className="upload-aside">
<Mascot small/>
<h3>You don’t have to figure it out alone.</h3>
<p>I’ll turn the questions into smaller, friendlier steps. You can type your answers, or say them out loud.</p>
<div className="aside-tip">
<span>✧</span>
<p>
<strong>Using several screenshots?</strong>Select them together in page order. Overlapping questions are combined automatically.</p>
</div>
</aside>
</div>
<p className="privacy-note">♧ Your form stays in temporary memory for up to an hour. Use sample data for this prototype.</p>{session&&<Link className="resume-link" href="/questions">Continue {session.filename} →</Link>}</>:!ready?<div className="empty-state" role="status">Finding your form…</div>:!session?<div className="empty-state">
<Mascot small/>
<h1>Let’s start with your form.</h1>
<p>Upload a document to begin your guided questions.</p>
<Link className="button primary" href="/upload">Upload a form ↗</Link>
</div>:stage==="questions"?<>
<div className="workspace-heading">
<div>
<p className="eyebrow">A LITTLE PROGRESS, ONE TASK AT A TIME</p>
<h1>Let’s do this <span>together.</span>
</h1>
</div>
<button className="button secondary" onClick={()=>{setMuted(!muted);localStorage.setItem("formfriend-muted",String(!muted));if(!muted){stopSpeech();}}}>{muted?"♩ Sound off":"♫ Sound on"}</button>
</div>
<div className="question-layout">
<aside className="companion-card">
<Mascot small talking={speaking}/>
<h3>{speaking?"I’m reading it for you…":"I’m right here with you."}</h3>
<p>There’s no rush. Take a breath, and we’ll work through this together.</p>
<div className="document-pill">▤ <span>{session.filename}</span>
</div>
<p className="mode-note">{session.mode==="mock"?"Demo questions · AI is not connected":session.simplification_status==="pending"||session.simplification_status==="running"?"Gemini is simplifying questions in the background…":session.simplification_status==="partial"?"Some questions could not be simplified":"Simplified with Gemini"}</p>
</aside>
<section className="question-card" aria-busy={busy}>
<div className="question-top">
<span>{field?.worksheet?.task_label||field?.eligibility_workflow?.task_label||(field?.table_lookup?"WAGE TABLE LOOKUP":field?.pay_period_calculation?"PER-PAYCHECK CALCULATION":`TASK ${index+1} OF ${session.fields.length}`)}</span>
<span>{Math.round(index/session.fields.length*100)}% complete</span>
</div>
<progress value={index} max={session.fields.length} aria-label="Tasks completed"/>
<div className="question-label">{field?.worksheet?.task_label||field?.eligibility_workflow?.task_label||(field?.table_lookup?"WAGE TABLE LOOKUP":field?.pay_period_calculation?"PER-PAYCHECK CALCULATION":"LET’S TAKE A SMALL STEP")}</div>
<h2 aria-live="polite">{fieldLoading?"Loading…":fieldFailed?"This question could not be simplified.":field?.simplified_question}</h2>{field?.helper_text&&<p className="helper-text">{field.helper_text}</p>}{field?.subquestions?.length&&!field?.calculation&&!field?.worksheet&&!field?.eligibility_workflow?<div className="subquestion-guide">
<strong>Let’s break it down:</strong>
<ul>{field.subquestions.map((item,i)=>
<li key={`${field.field_id}-sub-${i}`}>{item.text}</li>)}</ul>
</div>:null}{(fieldLoading||fieldFailed)&&<div className="field-simplification-state" role="status">
<span className="inline-loader" aria-hidden="true"/>
<p>{fieldLoading?"Gemini is working on this question. It will appear here as soon as it’s ready.":"Gemini did not return a valid result for this question."}</p>{index>0&&<button className="button secondary" type="button" onClick={()=>{setIndex(index-1);setValue(session.fields[index-1].user_response||"");}}>← Back</button>}</div>}<button hidden={fieldLoading||fieldFailed} className="text-button" onClick={read} disabled={muted}>♫ Read this question</button>
<details hidden={fieldLoading||fieldFailed} className="source-details">
<summary>ⓘ See more details</summary>
<p>
<strong>From {session.document_type==="image"?"screenshot":"page"} {field?.source_page}</strong>
</p>
<blockquote>{field?.original_question}</blockquote>{field?.worksheet&&<p>This field uses the {field.worksheet.title} included with your form.</p>}<p>This is the original wording from your document. Check it before answering.</p>{(!session.document_type||session.document_type==="pdf")&&<img className="source-preview" src={`${API}/sessions/${session.session_id}/fields/${encodeURIComponent(field?.field_id||"")}/source`} alt={`Page ${field?.source_page} of your form, with this field outlined in teal`} loading="lazy"/>}</details>
<form hidden={fieldLoading||fieldFailed} onSubmit={e=>{e.preventDefault();if(field?.worksheet||field?.eligibility_workflow||field?.table_lookup||field?.pay_period_calculation||field?.calculation)return;if(!field?.decision_tree||decisionComplete)void next();}}>
{field?.eligibility_workflow?<EligibilityWorkflow key={field.field_id} workflow={field.eligibility_workflow} busy={busy} sourceImageUrl={`${API}/sessions/${session.session_id}/fields/${encodeURIComponent(field.field_id)}/eligibility/source`} onRead={(step,text)=>void readEligibility(step,text)} onComplete={answer=>void next(answer)}/>
:field?.worksheet?<WorksheetWorkflow key={field.field_id} worksheet={field.worksheet} busy={busy} sourceImageUrl={`${API}/sessions/${session.session_id}/fields/${encodeURIComponent(field.field_id)}/worksheet/source`} onCalculate={async answers=>{const result=await request(`/sessions/${session.session_id}/fields/${encodeURIComponent(field.field_id)}/worksheet`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({answers})});return String(result.value);}} onComplete={answer=>void next(answer)}/>
:field?.table_lookup?<TableLookupWorkflow key={field.field_id} lookup={field.table_lookup} busy={busy} sourceImageUrl={`${API}/sessions/${session.session_id}/fields/${encodeURIComponent(field.field_id)}/table-lookup/source`} onLookup={async input=>{const result=await request(`/sessions/${session.session_id}/fields/${encodeURIComponent(field.field_id)}/table-lookup`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});return String(result.value);}} onComplete={answer=>void next(answer)}/>
:field?.pay_period_calculation?<PayPeriodCalculation key={field.field_id} calculation={field.pay_period_calculation} priorAnswers={Object.fromEntries(session.fields.map(item=>[item.field_id,item.user_response||""]))} busy={busy} onComplete={answer=>void next(answer)}/>
:field?.calculation?<GuidedCalculation key={field.field_id} questions={field.subquestions||[]} calculation={field.calculation} priorAnswers={Object.fromEntries(session.fields.map(item=>[item.field_id,item.user_response||""]))} busy={busy} onComplete={answer=>void next(answer)}/>
:field?.decision_tree?decisionComplete?<div className="decision-resolved">
<span>Selected form option</span>
<strong>{value}</strong>
<button type="button" className="text-button" onClick={()=>{setValue("");setDecisionPath([]);}}>Change answer</button>
</div>:decisionNode?<fieldset className="decision-card">
<legend>{decisionNode.question}</legend>{decisionNode.helper_text&&<p>{decisionNode.helper_text}</p>}<div className="decision-options">{decisionNode.answers.map(answer=>
<button key={answer.label} type="button" className="decision-option" disabled={busy} onClick={()=>chooseBranch(answer.label)}>{answer.label}<span>→</span>
</button>)}</div>{decisionPath.length>0&&<button type="button" className="text-button" onClick={()=>setDecisionPath(path=>path.slice(0,-1))}>← Previous step</button>}</fieldset>:<p role="alert">This guided question could not be displayed. See the original wording above.</p>:<>
<label htmlFor="answer">Your answer</label>
<textarea id="answer" rows={3} value={value} maxLength={5000} onChange={e=>setValue(e.target.value)} placeholder="Type your answer here…"/>
<div className="answer-tools">
<button type="button" className={`text-button ${listening?"listening":""}`} onClick={listen}>{listening?"● Listening… click to stop":"♩ Speak your answer"}</button>
<span>You can always edit this later.</span>
</div>
</>}<div className="question-actions" hidden={!!field?.worksheet||!!field?.eligibility_workflow||!!field?.table_lookup||!!field?.pay_period_calculation||!!field?.calculation}>
<button className="button secondary" type="button" disabled={busy||(index===0&&!decisionPath.length)} onClick={()=>{if(decisionPath.length){setDecisionPath(path=>path.slice(0,-1));return;}setDecisionPath([]);setIndex(index-1);setValue(session.fields[index-1].user_response||"");}}>← Back</button>{(!field?.decision_tree||decisionComplete)&&<button className="button primary" disabled={busy}>{busy?"Saving…":index===session.fields.length-1?"Review my answers":value.trim()?"Save & continue":"Skip for now"} <span>→</span>
</button>}</div>
</form>
</section>
</div>
<button className="resume-link" disabled={busy||simplifying} onClick={async()=>{if(!field)return;setBusy(true);try{remember(await saveField(field,value));router.push("/review");}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>Go to all answers →</button>
</>:<>
<div className="page-intro">
<p className="eyebrow">LOOK AT YOU. YOU DID THAT.</p>
<h1>A final look.<br/>
<span>Then you’re all set.</span>
</h1>
<p>Check your answers and edit anything you’d like before downloading.</p>
</div>
<div className="review-layout">
<section className="review-card">
<div className="review-title">
<h2>Your answers</h2>
<span>{session.fields.filter(f=>f.user_response?.trim()).length} / {session.fields.length} answered</span>
</div>{session.fields.map((f,i)=>
<div className="review-field" key={f.field_id}>
<label htmlFor={`review-${i}`}>
<span>{String(i+1).padStart(2,"0")}</span>{f.original_question}</label>
<textarea id={`review-${i}`} maxLength={5000} rows={2} placeholder="No answer yet — you can add one here." value={f.user_response||""} onBlur={e=>{void saveField(f,e.target.value).catch(err=>setError(err.message));}} onChange={e=>{setDownloaded(false);setSession({...session,fields:session.fields.map((item,j)=>j===i?{...item,user_response:e.target.value}:item)});}}/>
<small>{session.document_type==="image"?"Screenshot":"Page"} {f.source_page}</small>
</div>)}</section>
<aside className="download-card">
<Mascot small/>
<h3>One last check, friend.</h3>
<p>{answerSheet?"Your extracted answers will download as a text file. Upload a fillable document to fill the original.":session.document_type==="docx"?"Your answers will be added alongside the matching paragraphs in your Word document.":"Your answers will be placed in the original PDF’s fillable fields."}</p>
<div className="document-pill">▤ <span>{session.filename}</span>
</div>{session.fields.some(f=>!f.user_response?.trim())&&<p className="mode-note">Some answers are blank. You can complete them above or download as they are.</p>}<button className="button primary" disabled={busy} onClick={()=>void download()}>{busy?"Preparing…":"Download my document"} <span>↓</span>
</button>{downloaded&&<p className="success-message" role="status">✓ Your download is ready. Nicely done!</p>}<Link className="text-button" href="/questions">← Back to guided questions</Link>
<button className="text-button" disabled={busy} onClick={()=>void clear()}>Clear session & start fresh</button>
</aside>
</div>
</>}{error&&<div className="error-message" role="alert">{error}</div>}{notice&&<div className="notice-message" role="status">{notice}</div>}{session&&stage!=="upload"&&session.warnings.map(w=>
<p className="workflow-warning" key={w}>{w}</p>)}</main>
<Footer/>
</>;
}
