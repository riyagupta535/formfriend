"use client";
import { useEffect, useRef, useState } from "react";

/** Animate from the agent's output audio only; never sample the user's microphone. */
export function useAgentSpeechMouth(speaking: boolean, getOutputVolume?: () => number) {
  const [mouthOpen, setMouthOpen] = useState(0);
  const volume = useRef(getOutputVolume);
  volume.current = getOutputVolume;

  useEffect(() => {
    setMouthOpen(0);
    if (!speaking || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let active = true;
    let frame = 0;
    let smoothed = 0;
    let lastUpdate = -Infinity;
    const tick = (time: number) => {
      if (!active) return;
      let level = 0;
      try { level = volume.current?.() ?? 0; } catch { /* Playback can disconnect between frames. */ }
      const target = Number.isFinite(level) ? Math.min(1, Math.max(0, level - 0.015) * 4) : 0;
      smoothed += (target - smoothed) * 0.55;
      if (time - lastUpdate >= 32) {
        setMouthOpen(smoothed < 0.025 ? 0 : smoothed);
        lastUpdate = time;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => { active = false; cancelAnimationFrame(frame); };
  }, [speaking]);

  return mouthOpen;
}
