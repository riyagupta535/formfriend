import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import LanguagePage from './language-page';
const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); push.mockClear(); });
const reply = (body: object, ok = true) => Promise.resolve({ ok, json: async () => body });

it('chooses Spanish after upload and creates a guide without uploading or parsing again', async () => {
  sessionStorage.setItem('formfriend-session', 'upload');
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith('/sessions/upload') && !init) return reply({ session_id: 'upload', filename: 'my-form.pdf', language: 'en' });
    if (url.endsWith('/sessions/upload/language')) return reply({ session_id: 'upload', language: 'es' });
    if (url.endsWith('/from-upload')) return reply({ session_id: 'guided' });
    throw Error(`Unexpected ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<LanguagePage />);
  expect(await screen.findByText('Which language would you like Fomi to use?')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Question language'), { target: { value: 'es' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue to questions/ }));
  await waitFor(() => expect(push).toHaveBeenCalledWith('/guide'));
  const writes = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST');
  expect(writes.map(([url, init]) => [url, JSON.parse(init!.body as string)])).toEqual([
    ['http://localhost:8000/sessions/upload/language', { language: 'es' }],
    ['http://localhost:8000/agent/sessions/from-upload', { document_session_id: 'upload' }],
  ]);
  expect(sessionStorage.getItem('formfriend-session')).toBe('guided');
});

it('loads a saved selection on refresh and reuses an existing sample agent session', async () => {
  sessionStorage.setItem('formfriend-session', 'sample');
  const fetchMock = vi.fn((_url: string, init?: RequestInit) => reply(init
    ? { language: 'es' }
    : { session_id: 'sample', filename: 'Sample form', language: 'es', agent_state: { revision: 0 } }));
  vi.stubGlobal('fetch', fetchMock);
  render(<LanguagePage />);
  const language = await screen.findByLabelText('Question language');
  expect((language as HTMLSelectElement).value).toBe('es');
  fireEvent.click(screen.getByRole('button', { name: /Continue to questions/ }));
  await waitFor(() => expect(push).toHaveBeenCalledWith('/guide'));
  expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/from-upload'))).toBe(false);
  expect(sessionStorage.getItem('formfriend-session')).toBe('sample');
});

it('preserves the upload and selected language when continuing fails', async () => {
  sessionStorage.setItem('formfriend-session', 'upload');
  vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => init
    ? reply({ detail: 'Please try again.' }, false)
    : reply({ session_id: 'upload', filename: 'my-form.pdf', language: 'en' })));
  render(<LanguagePage />);
  fireEvent.change(await screen.findByLabelText('Question language'), { target: { value: 'es' } });
  fireEvent.click(screen.getByRole('button', { name: /Continue to questions/ }));
  expect((await screen.findByRole('alert')).textContent).toBe('Please try again.');
  expect((screen.getByLabelText('Question language') as HTMLSelectElement).value).toBe('es');
  expect(sessionStorage.getItem('formfriend-session')).toBe('upload');
  expect(push).not.toHaveBeenCalled();
});

it('shows an upload link when there is no document session', async () => {
  render(<LanguagePage />);
  expect(await screen.findByRole('link', { name: /Upload a form/ })).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Continue to questions/ })).toBeNull();
});

it.each(['en', 'es', 'zh', 'fil', 'vi', 'ar', 'fr', 'ko', 'pt', 'hi'])('carries the %s selection into the guided session', async code => {
  sessionStorage.setItem('formfriend-session', 'sample');
  const fetchMock = vi.fn((_url: string, init?: RequestInit) => reply(init ? { language: code }
    : { session_id: 'sample', filename: 'sample.pdf', language: 'en', agent_state: { revision: 0 } }));
  vi.stubGlobal('fetch', fetchMock);
  render(<LanguagePage />);
  const select = await screen.findByLabelText('Question language');
  expect(screen.getAllByRole('option').map(option => (option as HTMLOptionElement).value)).toEqual([
    'en', 'es', 'zh', 'fil', 'vi', 'ar', 'fr', 'ko', 'pt', 'hi',
  ]);
  fireEvent.change(select, { target: { value: code } });
  fireEvent.click(screen.getByRole('button', { name: /Continue to questions/ }));
  await waitFor(() => expect(push).toHaveBeenCalledWith('/guide'));
  expect(JSON.parse(fetchMock.mock.calls.find(([url]) => url.endsWith('/language'))![1]!.body as string)).toEqual({ language: code });
});
