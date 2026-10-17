"use client";
import Mascot from "../app/components/mascot";
import { useSpeechMouth } from "../lib/useSpeechMouth";
import { useCallback, useEffect, useRef, useState } from "react";

type Recognition = {
  lang: string; interimResults: boolean; continuous: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void; stop: () => void; abort: () => void;
};
type VoiceWindow = Window & {
  SpeechRecognition?: new () => Recognition;
  webkitSpeechRecognition?: new () => Recognition;
};
type Props = {
  question: string; fieldId: string; answer: string; onAnswer: (value: string) => void;
  disabled?: boolean; allowDictation?: boolean; autoPlay?: boolean;
  showAvatar?: boolean; onMouthChange?: (value: number) => void;
  onSpeakingChange?: (speaking: boolean) => void;
};
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function VoiceControls({
  question, fieldId, answer, onAnswer, disabled = false, allowDictation = true,
  autoPlay = false, onSpeakingChange, showAvatar = true, onMouthChange,
}: Props) {
  const {mouthOpen, trackAudio, stopMouth} = useSpeechMouth();
  useEffect(() => { onMouthChange?.(mouthOpen); }, [mouthOpen, onMouthChange]);
  const [state, setState] = useState("Ready");
  const [error, setError] = useState("");
  const [supported, setSupported] = useState(false);
  const [muted, setMuted] = useState(false);
  const [preferencesReady, setPreferencesReady] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);
  const recognition = useRef<Recognition | null>(null);
  const request = useRef<AbortController | null>(null);
  const url = useRef<string | null>(null);
  const generation = useRef(0);
  const latestAnswer = useRef(answer);
  const latestOnAnswer = useRef(onAnswer);
  latestAnswer.current = answer;
  latestOnAnswer.current = onAnswer;

  const cancelWork = useCallback(() => {
    stopMouth();
    generation.current++;
    request.current?.abort(); request.current = null;
    recognition.current?.abort(); recognition.current = null;
    audio.current?.pause(); audio.current = null;
    if (url.current) { URL.revokeObjectURL(url.current); url.current = null; }
  }, [stopMouth]);
  const stop = useCallback(() => { cancelWork(); setState("Ready"); }, [cancelWork]);

  useEffect(() => {
    const w = window as VoiceWindow;
    setSupported(!!(w.SpeechRecognition || w.webkitSpeechRecognition));
    try { setMuted(localStorage.getItem("formfriend-muted") === "true"); } catch { /* Storage may be disabled. */ }
    setPreferencesReady(true);
    return cancelWork;
  }, [cancelWork]);
  useEffect(() => { onSpeakingChange?.(state === "Speaking"); }, [state, onSpeakingChange]);
  useEffect(() => () => onSpeakingChange?.(false), [onSpeakingChange]);

  const speak = useCallback(async () => {
    stop();
    if (muted || disabled) return;
    setError(""); setState("Preparing audio");
    const current = generation.current;
    const controller = new AbortController(); request.current = controller;
    try {
      const response = await fetch(`${API}/voice/speech`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: question }), signal: controller.signal,
      });
      if (!response.ok) {
        const result = await response.json();
        throw Error(typeof result.detail === "string" ? result.detail : "Unable to play audio.");
      }
      const blob = await response.blob();
      if (current !== generation.current) return;
      url.current = URL.createObjectURL(blob);
      const player = new Audio(url.current); audio.current = player; trackAudio(player);
      player.onended = () => { if (current === generation.current) stop(); };
      player.onerror = () => {
        if (current === generation.current) { stop(); setError("Audio could not play. You can read the question above."); }
      };
      try { await player.play(); }
      catch { throw Error("Press Read question aloud to start ElevenLabs audio. Your browser may have blocked automatic playback."); }
      if (current === generation.current) setState("Speaking");
    } catch (e) {
      if (current !== generation.current) return;
      stop();
      setError(e instanceof Error ? e.message : "ElevenLabs audio is unavailable. Please try again.");
    }
  }, [question, muted, disabled, stop, trackAudio]);

  useEffect(() => {
    stop(); setError("");
    if (autoPlay && preferencesReady && !muted && !disabled) void speak();
    return cancelWork;
  }, [fieldId, question, autoPlay, preferencesReady, muted, disabled, speak, stop, cancelWork]);

  function listen() {
    stop(); setError("");
    if (disabled || !allowDictation) return;
    const w = window as VoiceWindow;
    const Constructor = w.SpeechRecognition || w.webkitSpeechRecognition;
    if (!Constructor) return;
    const current = generation.current;
    const mic = new Constructor(); recognition.current = mic;
    mic.lang = "en-US"; mic.interimResults = false; mic.continuous = false;
    mic.onresult = e => {
      if (current !== generation.current) return;
      const text = Array.from(e.results).map(r => r[0].transcript).join(" ");
      latestOnAnswer.current([latestAnswer.current, text].filter(Boolean).join(" "));
      setState("Check your answer");
    };
    mic.onerror = e => {
      if (current !== generation.current) return;
      setError(e.error === "not-allowed"
        ? "Microphone permission was denied. Allow access or type your answer."
        : "Could not hear your answer. Try again or type it.");
      setState("Ready");
    };
    mic.onend = () => {
      if (current === generation.current) {
        recognition.current = null;
        setState(s => s === "Listening" ? "Ready" : s);
      }
    };
    try { mic.start(); setState("Listening"); }
    catch { stop(); setError("Microphone could not start. Try again or type your answer."); }
  }

  return <section className="voice-controls" aria-label="Question audio and dictation">
    {showAvatar && <Mascot small talking={state === "Speaking"} mouthOpen={mouthOpen}/>}
    <div className="voice-actions">
      <button type="button" disabled={disabled || !preferencesReady || muted} onClick={() => void speak()}>Read question aloud</button>
      {allowDictation && <button type="button" disabled={disabled || !preferencesReady || !supported}
        onClick={state === "Listening" ? () => recognition.current?.stop() : listen}>
        {state === "Listening" ? "Finish speaking" : "Answer with microphone"}
      </button>}
      <button type="button" onClick={stop}>Stop</button>
      <button type="button" aria-pressed={muted} onClick={() => {
        stop(); setMuted(!muted);
        try { localStorage.setItem("formfriend-muted", String(!muted)); } catch { /* Optional preference. */ }
      }}>{muted ? "Unmute voice" : "Mute voice"}</button>
    </div>
    <p role="status" className="voice-status">{state === "Speaking" ? "Speaking · ElevenLabs" : state}</p>
    {allowDictation ? <p className="voice-help">Your transcript appears in the answer box. Edit it, then save and continue. Microphone audio may be processed by your browser’s speech service.</p>
      : <p className="voice-help">Listen to the question, then choose from the available answers.</p>}
    {allowDictation && !supported && <p className="voice-help">Speech recognition is unavailable in this browser. You can type your answer.</p>}

    {error && <p role="alert" className="voice-error">{error}</p>}
  </section>;
}
