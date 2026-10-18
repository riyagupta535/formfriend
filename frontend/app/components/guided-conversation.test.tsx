import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const tools: Record<string, (params: Record<string, unknown>) => Promise<string>> = {};
const hooks: { onMessage?: (m: { message: string; source: string }) => void } = {};
vi.mock('@elevenlabs/react', () => ({
  ConversationProvider: ({ children }: { children: React.ReactNode }) => children,
  useConversation: (options: { onMessage?: (m: { message: string; source: string }) => void }) => { hooks.onMessage = options.onMessage; return { status: 'disconnected', isSpeaking: false, isMuted: false, startSession: vi.fn(), endSession: vi.fn(), sendUserMessage: vi.fn(), setMuted: vi.fn() }; },
  useConversationClientTool: (name: string, handler: (params: Record<string, unknown>) => Promise<string>) => { tools[name] = handler; },
}));
import GuidedConversation from './guided-conversation';

const question = { id: 'kids', original_text: 'Qualifying children under 17', simplified_question: 'How many children under 17?', help_text: '',
  input_type: 'number', options: [], required: false, source_reference: { page: 1, section: 'Step 3' } };
const state = (revision: number, status = 'question') => ({ session_id: 's1', revision, status, question: status === 'question' ? question : null,
  progress: { answered: revision, unanswered: 1 - revision, skipped: 0, blocked: 0, not_applicable: 0 } });
const reply = (body: object, ok = true, status = 200) => Promise.resolve({ ok, status, json: async () => body });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('binds session and revision, parses JSON values, and shows learned words', async () => {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith('/next-question')) return reply(state(0));
    if (url.endsWith('/glossary')) return reply({ terms: [] });
    if (url.endsWith('/answers')) return reply({ saved: true, next: state(1, 'complete') });
    if (url.endsWith('/explain')) return reply({ saved: true, term: 'Qualifying child', glossary_size: 1 });
    throw Error(`unexpected ${url} ${init?.method}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<GuidedConversation sessionId="s1" />);
  expect(await screen.findByText('How many children under 17?')).toBeTruthy();

  await act(async () => { await tools.explain_term({ question_id: 'kids', term: 'Qualifying child', explanation: 'A child who meets the form rules.' }); });
  expect(JSON.parse(fetchMock.mock.calls.find(([u]) => u.endsWith('/explain'))![1]!.body as string))
    .toEqual({ question_id: 'kids', term: 'Qualifying child', explanation: 'A child who meets the form rules.', example: '' });
  expect(screen.getByText('Words you learned')).toBeTruthy();
  expect(screen.getByText('A child who meets the form rules.')).toBeTruthy();

  let result = '';
  await act(async () => { result = await tools.save_answer({ question_id: 'kids', value_json: '2', raw_response: 'two kids' }); });
  const [url, init] = fetchMock.mock.calls.find(([u]) => u.endsWith('/answers'))!;
  expect(url).toContain('/agent/sessions/s1/answers');
  expect(JSON.parse(init!.body as string)).toEqual({ question_id: 'kids', value: 2, raw_response: 'two kids', revision: 0 });
  expect(JSON.parse(result).saved).toBe(true);
  await waitFor(() => expect(screen.getByRole('link', { name: /Review my answers/ })).toBeTruthy());
});

it('returns backend validation errors to the agent instead of throwing', async () => {
  vi.stubGlobal('fetch', vi.fn((url: string) => url.endsWith('/answers')
    ? reply({ detail: 'The amount must be at least 0.' }, false, 422)
    : url.endsWith('/glossary') ? reply({ terms: [] }) : reply(state(0))));
  render(<GuidedConversation sessionId="s1" />);
  await screen.findByText('How many children under 17?');
  const result = await tools.save_answer({ question_id: 'kids', value_json: 'minus one', raw_response: 'minus one' });
  expect(JSON.parse(result)).toEqual({ error: 'The amount must be at least 0.', status: 422 });
});

it('shows what Forma says in the speech bubble and earlier answers as greyed history', async () => {
  vi.stubGlobal('fetch', vi.fn((url: string) => url.endsWith('/sessions/s1')
    ? reply({ fields: [
        { field_id: 'name', simplified_question: 'What is your name?', original_question: 'Name', user_response: 'Maria Lopez', status: 'answered' },
        { field_id: 'pets', simplified_question: 'Which pets?', original_question: 'Pets', user_response: '["Cat","Dog"]', status: 'answered' },
        { field_id: 'kids', simplified_question: 'How many children under 17?', original_question: 'Kids', user_response: null, status: 'unanswered' }] })
    : url.endsWith('/glossary') ? reply({ terms: [] }) : reply(state(0))));
  render(<GuidedConversation sessionId="s1" />);
  const toggle = await screen.findByRole('button', { name: /Earlier questions/ });
  expect(toggle.getAttribute('aria-expanded')).toBe('false');
  expect(screen.getByText('Last: Cat, Dog')).toBeTruthy();
  expect(screen.queryByText('Maria Lopez')).toBeNull();
  fireEvent.click(toggle);
  expect(toggle.getAttribute('aria-expanded')).toBe('true');
  expect(screen.getByText('Maria Lopez')).toBeTruthy();
  expect(screen.getByText('Cat, Dog')).toBeTruthy();
  expect(screen.getAllByRole('listitem')).toHaveLength(2);
  fireEvent.click(toggle);
  expect(screen.queryByText('Maria Lopez')).toBeNull();
  act(() => hooks.onMessage?.({ message: '[happy] How many children do you have?', source: 'ai' }));
  expect(screen.getByText('How many children do you have?')).toBeTruthy();
  act(() => hooks.onMessage?.({ message: 'two', source: 'user' }));
  expect(screen.getByText('“two”')).toBeTruthy();
  act(() => hooks.onMessage?.({ message: 'Got it.', source: 'ai' }));
  expect(screen.queryByText('“two”')).toBeNull();
});
