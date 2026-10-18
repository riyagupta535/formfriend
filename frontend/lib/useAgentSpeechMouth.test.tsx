import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useAgentSpeechMouth } from './useAgentSpeechMouth';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
function frames() {
  let tick: FrameRequestCallback = () => {};
  const cancel = vi.fn();
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => { tick = callback; return 1; }));
  vi.stubGlobal('cancelAnimationFrame', cancel);
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn(() => ({ matches: false })) });
  return { advance: (time: number) => act(() => tick(time)), cancel };
}
it('follows the output volume and closes after silence or speech ending', () => {
  const animation = frames();
  const volume = vi.fn(() => 0.25);
  const { result, rerender } = renderHook(({ speaking }) => useAgentSpeechMouth(speaking, volume), { initialProps: { speaking: true } });
  animation.advance(40);
  expect(result.current).toBeGreaterThan(0.3);
  volume.mockReturnValue(0);
  for (let time = 80; time < 400; time += 40) animation.advance(time);
  expect(result.current).toBe(0);
  volume.mockReturnValue(0.25); animation.advance(440);
  expect(result.current).toBeGreaterThan(0);
  rerender({ speaking: false });
  expect(result.current).toBe(0);
  expect(animation.cancel).toHaveBeenCalled();
});
it('does not read audio while the agent is not speaking', () => {
  frames(); const volume = vi.fn(() => 1);
  const { result } = renderHook(() => useAgentSpeechMouth(false, volume));
  expect(result.current).toBe(0);
  expect(requestAnimationFrame).not.toHaveBeenCalled();
  expect(volume).not.toHaveBeenCalled();
});
it('ignores unavailable or non-finite output levels and respects reduced motion', () => {
  const animation = frames();
  const { result, unmount } = renderHook(() => useAgentSpeechMouth(true, () => NaN));
  animation.advance(40); expect(result.current).toBe(0); unmount();
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn(() => ({ matches: true })) });
  vi.mocked(requestAnimationFrame).mockClear();
  renderHook(() => useAgentSpeechMouth(true, () => 1));
  expect(requestAnimationFrame).not.toHaveBeenCalled();
});
