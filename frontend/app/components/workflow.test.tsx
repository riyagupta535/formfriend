import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import Workflow from './workflow';

const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); push.mockClear(); });

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

it('keeps the upload page unchanged and opens the language step after parsing', async () => {
  const uploaded = { session_id: 'upload', filename: 'form.pdf', fields: [], warnings: [] };
  const fetchMock = vi.fn(async (_url: string, _options?: RequestInit) => ({ ok: true, json: async () => uploaded }));
  vi.stubGlobal('fetch', fetchMock);
  render(<Workflow stage="upload" />);
  expect(screen.queryByLabelText('Question language')).toBeNull();
  expect(screen.getByRole('button', { name: 'Choose a file' })).toBeTruthy();
  fireEvent.change(document.getElementById('document') as HTMLInputElement,
    { target: { files: [new File(['pdf'], 'form.pdf', { type: 'application/pdf' })] } });
  await waitFor(() => expect(push).toHaveBeenCalledWith('/language'));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(sessionStorage.getItem('formfriend-session')).toBe('upload');
});

it('opens language selection while background question simplification is still pending', async () => {
  const fetchMock = vi.fn(async (_url: string, _options?: RequestInit) => ({ ok: true, json: async () => ({
    session_id: 'upload', mode: 'gemini', simplification_status: 'pending', fields: [], warnings: [],
  }) }));
  vi.stubGlobal('fetch', fetchMock);
  render(<Workflow stage="upload" />);
  fireEvent.change(document.getElementById('document') as HTMLInputElement,
    { target: { files: [new File(['pdf'], 'form.pdf', { type: 'application/pdf' })] } });
  await waitFor(() => expect(push).toHaveBeenCalledWith('/language'));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect((fetchMock.mock.calls[0][1]!.body as FormData).get('language')).toBeNull();
});
