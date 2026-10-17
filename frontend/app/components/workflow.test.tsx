import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import Workflow from './workflow';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
class Mic {
  static current: Mic;
  onresult: ((e: unknown) => void) | null = null;
  onerror = null; onend = null;
  start = vi.fn(); stop = vi.fn(); abort = vi.fn();
  constructor() { Mic.current = this; }
}
afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('dictates into the real form field, confirms through the API, and discards stale dictation', async () => {
  sessionStorage.setItem('formfriend-session', 'integration');
  localStorage.setItem('formfriend-muted', 'true');
  Object.defineProperty(window, 'SpeechRecognition', { value: Mic, configurable: true });
  const session = {
    session_id: 'integration', filename: 'form.pdf', mode: 'mock', document_type: 'pdf', warnings: [],
    fields: [
      { field_id: 'name', original_question: 'Full name', simplified_question: 'Your full name?', source_page: 1, answer_type: 'text', user_response: null },
      { field_id: 'city', original_question: 'City', simplified_question: 'Your city?', source_page: 1, answer_type: 'text', user_response: null },
    ],
  };
  const fetchMock = vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/sessions/integration') && !options) return { ok: true, json: async () => session };
    if (url.endsWith('/sessions/integration/fields/name') && options?.method === 'POST') {
      const body = JSON.parse(options.body as string);
      return { ok: true, json: async () => ({ ...session, fields: session.fields.map(f => f.field_id === 'name' ? { ...f, user_response: body.value, confirmed: body.confirmed } : f) }) };
    }
    throw Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<Workflow stage="questions" />);
  await screen.findByRole('heading', { name: 'Your full name?' });
  await screen.findByText('Unmute voice');
  fireEvent.click(screen.getByText('Answer with microphone'));
  const oldMic = Mic.current;
  act(() => oldMic.onresult?.({ results: [[{ transcript: 'Alex Example' }]] }));
  expect((screen.getByLabelText('Your answer') as HTMLTextAreaElement).value).toBe('Alex Example');
  fireEvent.click(screen.getByText(/Save & continue/));
  await screen.findByRole('heading', { name: 'Your city?' });
  await waitFor(() => expect(oldMic.abort).toHaveBeenCalled());
  const save = fetchMock.mock.calls.find(([url, options]) => url.endsWith('/fields/name') && options?.method === 'POST');
  expect(JSON.parse(save?.[1].body)).toEqual({ value: 'Alex Example', confirmed: true });
  act(() => oldMic.onresult?.({ results: [[{ transcript: 'stale name' }]] }));
  expect((screen.getByLabelText('Your answer') as HTMLTextAreaElement).value).toBe('');
});
