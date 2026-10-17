"use client";
import Mascot from "../app/components/mascot";
import { useSpeechMouth } from "../lib/useSpeechMouth";
import { useEffect, useRef, useState } from "react";
type Recognition = {
 lang:string; interimResults:boolean; continuous:boolean;
 onresult:((e:{results:ArrayLike<ArrayLike<{transcript:string}>>})=>void)|null;
 onerror:((e:{error:string})=>void)|null; onend:(()=>void)|null;
 start:()=>void; stop:()=>void; abort:()=>void;
};
type VoiceWindow = Window & { SpeechRecognition?:new()=>Recognition; webkitSpeechRecognition?:new()=>Recognition };
type Props = { question:string; fieldId:string; answer:string; onAnswer:(value:string)=>void; disabled?:boolean };
const API=process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000";
export default function VoiceControls({question,fieldId,answer,onAnswer,disabled=false}:Props) {
 const {mouthOpen,trackAudio,stopMouth}=useSpeechMouth();
 const [state,setState]=useState("Ready"),[error,setError]=useState(""),[supported,setSupported]=useState(false),[muted,setMuted]=useState(false);
 const audio=useRef<HTMLAudioElement|null>(null), recognition=useRef<Recognition|null>(null), request=useRef<AbortController|null>(null), url=useRef<string|null>(null), generation=useRef(0), latestAnswer=useRef(answer);
 latestAnswer.current=answer;
 function stop(){stopMouth();generation.current++;request.current?.abort();request.current=null;recognition.current?.abort();recognition.current=null;audio.current?.pause();audio.current=null;if(url.current){URL.revokeObjectURL(url.current);url.current=null;}setState("Ready");}
 useEffect(()=>{const w=window as VoiceWindow;setSupported(!!(w.SpeechRecognition||w.webkitSpeechRecognition));return ()=>{generation.current++;request.current?.abort();recognition.current?.abort();audio.current?.pause();if(url.current)URL.revokeObjectURL(url.current);};},[]);
 useEffect(()=>{stop();setError("");},[fieldId,question]); // Cancel stale speech and transcripts when navigating.
 async function speak(){stop();if(muted)return;setError("");setState("Preparing audio");const current=generation.current;const controller=new AbortController();request.current=controller;
 try{const response=await fetch(`${API}/voice/speech`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:question}),signal:controller.signal});if(!response.ok){const result=await response.json();throw Error(result.detail||"Unable to play audio.");}const blob=await response.blob();if(current!==generation.current)return;url.current=URL.createObjectURL(blob);const player=new Audio(url.current);audio.current=player;trackAudio(player);player.onended=()=>{if(current===generation.current)stop();};player.onerror=()=>{if(current===generation.current){stop();setError("Audio could not play. You can read the question above.");}};await player.play();if(current===generation.current)setState("Speaking");}catch(e){if(current!==generation.current)return;stop();setError(e instanceof Error?e.message:"Audio unavailable.");}}
 function listen(){stop();setError("");const w=window as VoiceWindow;const Constructor=w.SpeechRecognition||w.webkitSpeechRecognition;if(!Constructor)return;const current=generation.current;const mic=new Constructor();recognition.current=mic;mic.lang="en-US";mic.interimResults=false;mic.continuous=false;
 mic.onresult=e=>{if(current!==generation.current)return;const text=Array.from(e.results).map(r=>r[0].transcript).join(" ");onAnswer([latestAnswer.current,text].filter(Boolean).join(" "));setState("Check your answer");};
 mic.onerror=e=>{if(current!==generation.current)return;setError(e.error==="not-allowed"?"Microphone permission was denied. Allow access or type your answer.":"Could not hear your answer. Try again or type it.");setState("Ready");};
 mic.onend=()=>{if(current===generation.current){recognition.current=null;setState(s=>s==="Listening"?"Ready":s);}};
 try{mic.start();setState("Listening");}catch{stop();setError("Microphone could not start. Try again or type your answer.");}}
 return <div className="mb-5 rounded-xl bg-green-50 p-4"><Mascot small talking={state==="Speaking"} mouthOpen={mouthOpen}/><div className="flex flex-wrap gap-2"><button type="button" disabled={disabled||muted} onClick={()=>void speak()} className="rounded-full border px-4">Read question aloud</button><button type="button" disabled={disabled||!supported} onClick={state==="Listening"?()=>recognition.current?.stop():listen} className="rounded-full border px-4">{state==="Listening"?"Finish speaking":"Answer with microphone"}</button><button type="button" onClick={stop} className="rounded-full border px-4">Stop</button><button type="button" aria-pressed={muted} onClick={()=>{stop();setMuted(!muted);}} className="rounded-full border px-4">{muted?"Unmute voice":"Mute voice"}</button></div><p role="status" className="mt-3 text-sm">{state}</p><p className="mt-2 text-sm">Your transcript appears below. Edit it, then select Confirm and continue. Microphone audio may be processed by your browser’s speech service.</p>{!supported&&<p className="mt-2 text-sm">Speech recognition is unavailable in this browser. You can type your answer.</p>}{error&&<p role="alert" className="mt-2 text-red-900">{error}</p>}</div>;
}
