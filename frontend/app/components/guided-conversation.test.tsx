import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const calls = vi.hoisted(() => ({start:vi.fn().mockResolvedValue('conversation'),context:vi.fn()}));
const tools: Record<string, (params: Record<string, unknown>) => Promise<string>> = {};
vi.mock('@elevenlabs/react', () => ({
  ConversationProvider: ({ children }: { children: React.ReactNode }) => children,
  useConversation: () => ({ status: 'disconnected', isSpeaking: false, isMuted: false, startSession: calls.start, sendContextualUpdate:calls.context, endSession: vi.fn(), sendUserMessage: vi.fn(), setMuted: vi.fn() }),
  useConversationClientTool: (name: string, handler: (params: Record<string, unknown>) => Promise<string>) => { tools[name] = handler; },
}));
import GuidedConversation from './guided-conversation';

const question = { id: 'kids', original_text: 'Qualifying children under 17', simplified_question: 'How many children under 17?', help_text: '',
  input_type: 'number', options: [], required: false, source_reference: { page: 1, section: 'Step 3' } };
const state = (revision: number, status = 'question') => ({ session_id: 's1', revision, status, question: status === 'question' ? question : null,
  progress: { answered: revision, unanswered: 1 - revision, skipped: 0, blocked: 0, not_applicable: 0 } });
const reply = (body: object, ok = true, status = 200) => Promise.resolve({ ok, status, json: async () => body });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); calls.start.mockClear();calls.context.mockClear(); });

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


it('uses the introduction once and resumes at the latest question after a break',async()=>{
 let revision=0;
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/agent-session')?reply({signed_url:'wss://synthetic'})
   :url.endsWith('/glossary')?reply({terms:[]}):reply({...state(revision),question:revision?{...question,id:'income',simplified_question:'What is your annual income?'}:question})));
 render(<GuidedConversation sessionId="s1"/>);
 await screen.findByText('How many children under 17?');
 fireEvent.click(screen.getByRole('button',{name:/Start talking/}));
 await screen.findByRole('button',{name:/Keep going/});
 expect(calls.start.mock.calls[0][0].overrides).toBeUndefined();
 revision=1;
 fireEvent.click(screen.getByRole('button',{name:/Keep going/}));
 await waitFor(()=>expect(calls.start).toHaveBeenCalledTimes(2));
 expect(calls.start.mock.calls[1][0].overrides).toEqual({agent:{firstMessage:'What is your annual income?'}});
 await waitFor(()=>expect(calls.context).toHaveBeenCalledOnce());
 expect(calls.context.mock.calls[0][0]).toContain('Do not repeat your introduction');
});

it('skips the introduction for a session with existing saved progress',async()=>{
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/agent-session')?reply({signed_url:'wss://synthetic'})
   :url.endsWith('/glossary')?reply({terms:[]}):reply(state(1))));
 render(<GuidedConversation sessionId="s1"/>);
 fireEvent.click(await screen.findByRole('button',{name:/Keep going/}));
 await waitFor(()=>expect(calls.start).toHaveBeenCalledOnce());
 expect(calls.start.mock.calls[0][0].overrides.agent.firstMessage).toBe('How many children under 17?');
});
