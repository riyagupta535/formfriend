import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useSpeechMouth } from './useSpeechMouth';
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('follows question volume, closes on silence, and releases audio resources', () => {
  let tick: FrameRequestCallback = () => {};
  let loud = true;
  const disconnect = vi.fn(), close = vi.fn().mockResolvedValue(undefined);
  const analyser = { fftSize: 256, connect: vi.fn(), disconnect,
    getByteTimeDomainData: (data: Uint8Array) => data.fill(loud ? 160 : 128) };
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback) => { tick = callback; return 1; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.stubGlobal('AudioContext', class {
    destination = {};
    createMediaElementSource = () => ({ connect: vi.fn(), disconnect });
    createAnalyser = () => analyser;
    resume = vi.fn().mockResolvedValue(undefined);
    close = close;
  });
  const audio = document.createElement('audio');
  Object.defineProperty(audio, 'paused', { value: false });
  const { result, unmount } = renderHook(() => useSpeechMouth());
  act(() => result.current.trackAudio(audio));
  act(() => tick(40));
  expect(result.current.mouthOpen).toBeGreaterThan(0);
  loud = false;
  for (let i = 2; i < 15; i++) act(() => tick(i * 40));
  expect(result.current.mouthOpen).toBe(0);
  act(() => result.current.stopMouth());
  expect(close).toHaveBeenCalledOnce();
  expect(disconnect).toHaveBeenCalledTimes(2);
  expect(cancelAnimationFrame).toHaveBeenCalled();
  unmount();
});
