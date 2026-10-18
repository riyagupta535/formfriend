import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import Workflow from './workflow';

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('accepts valid document and screenshot extensions', async () => {
  const uploaded = {
    session_id: 'upload', filename: 'form.pdf', mode: 'mock', document_type: 'pdf', warnings: [],
    fields: [{ field_id: 'name', original_question: 'Full name', simplified_question: 'Your full name?', source_page: 1, answer_type: 'text', user_response: null }],
  };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => uploaded });
  vi.stubGlobal('fetch', fetchMock);
  render(<Workflow stage="upload" />);

  const input = document.getElementById('document') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(['pdf'], 'form.pdf', { type: 'application/pdf' })] } });

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  const [, options] = fetchMock.mock.calls[0];
  expect((options.body as FormData).get('file')).toBeInstanceOf(File);
  expect(screen.queryByText('Choose a PDF, DOCX, PNG, or JPG file.')).toBeNull();
});

it('turns an upload into a guided conversation and opens it', async () => {
  const guidedSession = { session_id: 'guided', filename: 'form.pdf', mode: 'mock', document_type: 'pdf', warnings: [], fields: [] };
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/sessions') && options?.method === 'POST') return { ok: true, json: async () => ({ session_id: 'upload' }) };
    if (url.endsWith('/agent/sessions/from-upload')) return { ok: true, json: async () => ({ session_id: 'guided' }) };
    if (url.endsWith('/sessions/guided')) return { ok: true, json: async () => guidedSession };
    throw Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<Workflow stage="upload" />);
  fireEvent.change(document.getElementById('document') as HTMLInputElement,
    { target: { files: [new File(['pdf'], 'form.pdf', { type: 'application/pdf' })] } });
  await waitFor(() => expect(push).toHaveBeenCalledWith('/guide'));
  const bridge = fetchMock.mock.calls.find(([url]) => url.endsWith('/from-upload'))!;
  expect(JSON.parse(bridge[1]!.body as string)).toEqual({ document_session_id: 'upload' });
  expect(sessionStorage.getItem('formfriend-session')).toBe('guided');
});

it('opens the guide immediately while Gemini simplification is pending', async () => {
  const calls: string[] = [];
  const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
    calls.push(url);
    if (url.endsWith('/sessions') && options?.method === 'POST') return { ok: true, json: async () => ({
      session_id: 'upload', mode: 'gemini', simplification_status: 'pending', fields: [], warnings: [],
    }) };
    if (url.endsWith('/agent/sessions/from-upload')) return { ok: true, json: async () => ({ session_id: 'guided' }) };
    if (url.endsWith('/sessions/guided')) return { ok: true, json: async () => ({ session_id: 'guided', fields: [], warnings: [] }) };
    throw Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<Workflow stage="upload" />);

  fireEvent.change(document.getElementById('document') as HTMLInputElement,
    { target: { files: [new File(['pdf'], 'form.pdf', { type: 'application/pdf' })] } });

  await waitFor(() => expect(push).toHaveBeenCalledWith('/guide'), { timeout: 2000 });
  expect(calls).not.toContain('http://localhost:8000/sessions/upload');
  expect(calls).toContain('http://localhost:8000/agent/sessions/from-upload');
});
