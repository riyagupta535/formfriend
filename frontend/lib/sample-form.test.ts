import { afterEach, expect, it, vi } from 'vitest';
import { startSampleSession } from './sample-form';
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });
it('starts a Spanish sample with the supported backend validation schema', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ session_id: 'spanish-demo' }) });
  vi.stubGlobal('fetch', fetchMock);
  expect(await startSampleSession('es')).toBe('spanish-demo');
  const request = JSON.parse(fetchMock.mock.calls[0][1].body);
  expect(request.language).toBe('es');
  expect(request.questions[0].validation).toEqual({ kind: 'person_name' });
  expect(request.questions.every((question: { validation: unknown }) => question.validation != null)).toBe(true);
  expect(sessionStorage.getItem('formfriend-session')).toBe('spanish-demo');
});
