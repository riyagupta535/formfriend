"use client";
import { useCallback, useEffect, useRef, useState } from "react";

// Analyse only the question audio, never the user's microphone.
export function useSpeechMouth() {
  const [mouthOpen, setMouthOpen] = useState(0);
  const cleanup = useRef<(() => void) | null>(null);
  const stopMouth = useCallback(() => {
    cleanup.current?.();
    cleanup.current = null;
    setMouthOpen(0);
  }, []);
  const trackAudio = useCallback((audio: HTMLAudioElement) => {
    stopMouth();
    if (!window.AudioContext) return;
    let context: AudioContext | undefined;
    try {
      context = new AudioContext();
      const source = context.createMediaElementSource(audio);
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyser.connect(context.destination);
      const samples = new Uint8Array(analyser.fftSize);
      let frame = 0;
      let previous = 0;
      let lastUpdate = 0;
      const tick = (time: number) => {
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const sample of samples) sum += ((sample - 128) / 128) ** 2;
        const target = audio.paused || audio.ended ? 0 : Math.min(1, Math.max(0, Math.sqrt(sum / samples.length) - .012) * 9);
        previous += (target - previous) * .55;
        if (time - lastUpdate > 32) {
          setMouthOpen(previous < .025 ? 0 : previous);
          lastUpdate = time;
        }
        frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
      const resume = () => { void context?.resume().catch(() => {}); };
      audio.addEventListener("play", resume);
      resume();
      cleanup.current = () => {
        cancelAnimationFrame(frame);
        audio.removeEventListener("play", resume);
        source.disconnect();
        analyser.disconnect();
        void context?.close().catch(() => {});
      };
    } catch {
      // Animation is optional; retain playback on browsers without Web Audio.
      void context?.close().catch(() => {});
    }
  }, [stopMouth]);
  useEffect(() => () => cleanup.current?.(), []);
  return { mouthOpen, trackAudio, stopMouth };
}
