import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const calls = vi.hoisted(() => ({start:vi.fn().mockResolvedValue('conversation'),context:vi.fn(),send:vi.fn(),activity:vi.fn(),mute:vi.fn(),status:'disconnected',onMessage:undefined as undefined | ((event:{message:string;source:string})=>void)}));
const tools: Record<string, (params: Record<string, unknown>) => Promise<string>> = {};
vi.mock('@elevenlabs/react', () => ({
  ConversationProvider: ({ children }: { children: React.ReactNode }) => children,
  useConversation: (options: {onMessage:typeof calls.onMessage}) => {calls.onMessage=options.onMessage;return ({ status: calls.status, isSpeaking: false, isMuted: false, startSession: calls.start, sendContextualUpdate:calls.context, endSession: vi.fn(), sendUserMessage: calls.send, sendUserActivity:calls.activity, setMuted:calls.mute });},
  useConversationClientTool: (name: string, handler: (params: Record<string, unknown>) => Promise<string>) => { tools[name] = handler; },
}));
import GuidedConversation from './guided-conversation';

const question = { id: 'kids', original_text: 'Qualifying children under 17', simplified_question: 'How many children under 17?', help_text: '',
  input_type: 'number', options: [], required: false, source_reference: { page: 1, section: 'Step 3' } };
const state = (revision: number, status = 'question') => ({ session_id: 's1', revision, status, question: status === 'question' ? question : null,
  progress: { answered: revision, unanswered: 1 - revision, skipped: 0, blocked: 0, not_applicable: 0 } });
const reply = (body: object, ok = true, status = 200) => Promise.resolve({ ok, status, json: async () => body });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); calls.start.mockClear();calls.context.mockClear();calls.send.mockReset();calls.activity.mockClear();calls.mute.mockClear();calls.status='disconnected'; });

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

it('shows typed input while voice is disconnected and saves directly to the backend', async () => {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith('/next-question')) return reply(state(0));
    if (url.endsWith('/glossary')) return reply({ terms: [] });
    if (url.endsWith('/typed-answers')) return reply({ saved: true, next: state(1, 'complete') });
    throw Error(`unexpected ${url} ${init?.method}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<GuidedConversation sessionId="s1" />);

  const input = await screen.findByRole('textbox', { name: 'Type your answer or ask a question' });
  fireEvent.change(input, { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));

  await waitFor(() => expect(screen.getByRole('link', { name: /Review my answers/ })).toBeTruthy());
  const [, init] = fetchMock.mock.calls.find(([url]) => url.endsWith('/typed-answers'))!;
  expect(JSON.parse(init!.body as string)).toEqual({ question_id: 'kids', text: '2', revision: 0 });
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
 await waitFor(()=>expect(calls.context.mock.calls.some(([text])=>text.includes('Do not repeat your introduction'))).toBe(true));
});

it('skips the introduction for a session with existing saved progress',async()=>{
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/agent-session')?reply({signed_url:'wss://synthetic'})
   :url.endsWith('/glossary')?reply({terms:[]}):reply(state(1))));
 render(<GuidedConversation sessionId="s1"/>);
 fireEvent.click(await screen.findByRole('button',{name:/Keep going/}));
 await waitFor(()=>expect(calls.start).toHaveBeenCalledOnce());
 expect(calls.start.mock.calls[0][0].overrides.agent.firstMessage).toBe('How many children under 17?');
});

it('keeps speech and typed messages in the same live conversation without restarting or saving directly',async()=>{
 calls.status='connected';
 const fetchMock=vi.fn((url:string)=>url.endsWith('/glossary')?reply({terms:[]}):reply(state(0)));
 vi.stubGlobal('fetch',fetchMock);
 render(<GuidedConversation sessionId="s1"/>);
 await screen.findByText('How many children under 17?');
 act(()=>calls.onMessage!({source:'user',message:'I have two children'}));
 const input=screen.getByRole('textbox',{name:'Type your answer or ask a question'});
 fireEvent.change(input,{target:{value:'What does qualifying mean?'}});
 expect(calls.activity).toHaveBeenCalledOnce();
 fireEvent.click(screen.getByRole('button',{name:'Send'}));
 expect(calls.send).toHaveBeenCalledWith('What does qualifying mean?');
 expect(screen.getByText('I have two children')).toBeTruthy();
 expect(screen.getByText('What does qualifying mean?')).toBeTruthy();
 act(()=>calls.onMessage!({source:'user',message:'Yes, both are under seventeen'}));
 expect(screen.getByText('Yes, both are under seventeen')).toBeTruthy();
 expect(calls.start).not.toHaveBeenCalled();expect(calls.mute).not.toHaveBeenCalled();
 expect(fetchMock.mock.calls.some(([url])=>url.endsWith('/typed-answers'))).toBe(false);
 expect((input as HTMLInputElement).value).toBe('');
});

it('keeps the typed draft when sending to the live conversation fails',async()=>{
 calls.status='connected';calls.send.mockImplementation(()=>{throw Error('Disconnected');});
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/glossary')?reply({terms:[]}):reply(state(0))));
 render(<GuidedConversation sessionId="s1"/>);
 await screen.findByText('How many children under 17?');
 const input=screen.getByRole('textbox',{name:'Type your answer or ask a question'});
 fireEvent.change(input,{target:{value:'My draft'}});fireEvent.click(screen.getByRole('button',{name:'Send'}));
 expect((input as HTMLInputElement).value).toBe('My draft');
 expect(screen.getByRole('alert').textContent).toContain('could not be sent');
});

it('preserves typed-only answer saving when voice is disconnected',async()=>{
 const fetchMock=vi.fn((url:string)=>url.endsWith('/glossary')?reply({terms:[]}):url.endsWith('/typed-answers')?reply({saved:true,next:state(1,'complete')}):reply(state(0)));
 vi.stubGlobal('fetch',fetchMock);
 render(<GuidedConversation sessionId="s1"/>);
 const input=await screen.findByRole('textbox',{name:'Type your answer or ask a question'});
 fireEvent.change(input,{target:{value:'2'}});fireEvent.click(screen.getByRole('button',{name:'Send'}));
 await screen.findByRole('link',{name:/Review my answers/});
 expect(calls.send).not.toHaveBeenCalled();expect(calls.start).not.toHaveBeenCalled();
 expect(screen.getByText('2')).toBeTruthy();
});

it('shows a typed-answer follow-up and stays on the same question without advancing',async()=>{
 const fetchMock=vi.fn((url:string)=>url.endsWith('/glossary')?reply({terms:[]}):url.endsWith('/typed-answers')?reply({saved:false,reply:'Please give the number of children under 17.',next:state(0)}):reply(state(0)));
 vi.stubGlobal('fetch',fetchMock);
 render(<GuidedConversation sessionId="s1"/>);
 const input=await screen.findByRole('textbox',{name:'Type your answer or ask a question'});
 fireEvent.change(input,{target:{value:'I like pizza'}});fireEvent.click(screen.getByRole('button',{name:'Send'}));
 expect(await screen.findByText('Please give the number of children under 17.')).toBeTruthy();
 expect(screen.getByText('How many children under 17?')).toBeTruthy();
 expect(screen.queryByRole('link',{name:/Review my answers/})).toBeNull();
});
