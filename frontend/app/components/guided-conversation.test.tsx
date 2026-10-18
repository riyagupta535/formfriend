import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

const calls = vi.hoisted(() => ({start:vi.fn().mockResolvedValue('conversation'),context:vi.fn(),send:vi.fn(),activity:vi.fn(),mute:vi.fn(),status:'disconnected',speaking:false,volume:vi.fn(()=>0.25),onMessage:undefined as undefined | ((event:{message:string;source:string})=>void)}));
const tools: Record<string, (params: Record<string, unknown>) => Promise<string>> = {};
vi.mock('@elevenlabs/react', () => ({
  ConversationProvider: ({ children }: { children: React.ReactNode }) => children,
  useConversation: (options: {onMessage:typeof calls.onMessage}) => {calls.onMessage=options.onMessage;return ({ status: calls.status, isSpeaking: calls.speaking, getOutputVolume: calls.volume, isMuted: false, startSession: calls.start, sendContextualUpdate:calls.context, endSession: vi.fn(), sendUserMessage: calls.send, sendUserActivity:calls.activity, setMuted:calls.mute });},
  useConversationClientTool: (name: string, handler: (params: Record<string, unknown>) => Promise<string>) => { tools[name] = handler; },
}));
import GuidedConversation from './guided-conversation';

const question = { id: 'kids', original_text: 'Qualifying children under 17', simplified_question: 'How many children under 17?', help_text: '',
  input_type: 'number', options: [], required: false, source_reference: { page: 1, section: 'Step 3' } };
const state = (revision: number, status = 'question') => ({ session_id: 's1', revision, status, question: status === 'question' ? question : null,
  progress: { answered: revision, unanswered: 1 - revision, skipped: 0, blocked: 0, not_applicable: 0 } });
const reply = (body: object, ok = true, status = 200) => Promise.resolve({ ok, status, json: async () => body });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); calls.start.mockClear();calls.context.mockClear();calls.send.mockReset();calls.activity.mockClear();calls.mute.mockClear();calls.status='disconnected';calls.speaking=false; });

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
    if (url.endsWith('/answers')) return reply({ saved: true, next: state(1, 'complete') });
    throw Error(`unexpected ${url} ${init?.method}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<GuidedConversation sessionId="s1" />);

  const input = await screen.findByLabelText('Type your answer');
  fireEvent.change(input, { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));

  await waitFor(() => expect(screen.getByRole('link', { name: /Review my answers/ })).toBeTruthy());
  const [, init] = fetchMock.mock.calls.find(([url]) => url.endsWith('/answers'))!;
  expect(JSON.parse(init!.body as string)).toEqual({ question_id: 'kids', value: 2, raw_response: '2', revision: 0 });

  fireEvent.click(screen.getByRole('button', { name: '← Back' }));
  expect(screen.getByText('How many children under 17?')).toBeTruthy();
  expect((screen.getByLabelText('Type your answer') as HTMLInputElement).value).toBe('2');
  expect(screen.getByText('Update this answer, then press Send to continue.')).toBeTruthy();
});

it('shows deterministic validation errors and stays on the current typed question', async () => {
  const validationQuestion = { ...question, input_type: 'text', simplified_question: 'What is your Social Security number?' };
  const validationState = { ...state(0), question: validationQuestion };
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
    if (url.endsWith('/next-question')) return reply(validationState);
    if (url.endsWith('/glossary')) return reply({ terms: [] });
    if (url.endsWith('/answers')) return reply(
      { detail: 'Enter a 9-digit Social Security number in the format XXX-XX-XXXX.' }, false, 422,
    );
    throw Error(`unexpected ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<GuidedConversation sessionId="s1" />);

  const input = await screen.findByLabelText('Type your answer');
  fireEvent.change(input, { target: { value: 'lkj' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));

  expect((await screen.findByRole('alert')).textContent).toContain(
    'Enter a 9-digit Social Security number in the format XXX-XX-XXXX.',
  );
  expect(screen.getByText('What is your Social Security number?')).toBeTruthy();
  expect((input as HTMLInputElement).value).toBe('lkj');
});
it('shows choice options as buttons and saves a clicked option', async () => {
  const choice = { ...question, id: 'status', input_type: 'choice', simplified_question: 'Which filing status fits you?',
    options: ['Single', 'Married filing jointly', 'Head of household'] };
  const choiceState = { ...state(0), question: choice };
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
    if (url.endsWith('/next-question')) return reply(choiceState);
    if (url.endsWith('/glossary')) return reply({ terms: [] });
    if (url.endsWith('/answers')) return reply({ saved: true, next: state(1, 'complete') });
    throw Error(`unexpected ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<GuidedConversation sessionId="s1" />);

  fireEvent.click(await screen.findByRole('button', { name: /Married filing jointly/ }));
  await waitFor(() => expect(screen.getByRole('link', { name: /Review my answers/ })).toBeTruthy());
  const [, init] = fetchMock.mock.calls.find(([url]) => url.endsWith('/answers'))!;
  expect(JSON.parse(init!.body as string)).toEqual({
    question_id: 'status', value: 'Married filing jointly', raw_response: 'Married filing jointly', revision: 0,
  });
});

it('shows Gemini subquestions and saves their deterministic calculation', async () => {
  const calculationQuestion = {
    ...question,
    simplified_question: 'Calculate your total credit amount for qualifying children under age 17.',
    input_type: 'currency',
    subquestions: [
      { text: 'Is your income within the limit for this credit?', helper_text: 'The limit depends on your filing status.', answer_type: 'choice', options: ['Yes', 'No'] },
      { text: 'How many qualifying children under age 17 do you have?', helper_text: null, answer_type: 'number', options: [] },
    ],
    calculation: {
      operation: 'multiply', input_question_indices: [1], factor: 2200,
      source_question_numbers: [], source_field_ids: [], condition_question_index: 0,
      condition_answer: 'Yes', condition_zero_answers: ['No'], condition_skip_answers: [],
      condition_failure_message: 'This credit does not apply based on that answer.',
    },
  };
  const calculationState = { ...state(0), question: calculationQuestion, prior_answers: {} };
  const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
    if (url.endsWith('/next-question')) return reply(calculationState);
    if (url.endsWith('/glossary')) return reply({ terms: [] });
    if (url.endsWith('/answers')) return reply({ saved: true, next: state(1, 'complete') });
    throw Error(`unexpected ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<GuidedConversation sessionId="s1" />);

  fireEvent.click(await screen.findByRole('button', { name: /^Yes/ }));
  expect(screen.getByText('How many qualifying children under age 17 do you have?')).toBeTruthy();
  expect(screen.queryByRole('textbox', { name: 'Type your answer' })).toBeNull();
  fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: /Calculate/ }));
  expect(screen.getByText('$4,400')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: /Save & continue/ }));

  await waitFor(() => expect(screen.getByRole('link', { name: /Review my answers/ })).toBeTruthy());
  const [, init] = fetchMock.mock.calls.find(([url]) => url.endsWith('/answers'))!;
  expect(JSON.parse(init!.body as string)).toEqual({
    question_id: 'kids', value: 4400, raw_response: '4400', revision: 0,
  });
});

it('shows the existing worksheet workflow instead of a generic textbox', async () => {
  const worksheetQuestion = {
    ...question,
    id: 'deductions',
    input_type: 'currency',
    simplified_question: 'Would you like help figuring out whether to enter an amount for deductions?',
    help_text: 'You can use the worksheet, enter a result you already know, or leave this blank.',
    worksheet: {
      worksheet_id: 'w4-deductions', task_label: 'Deductions', title: 'Deductions Worksheet',
      source_page: 4, result_line: '15', intro_question: 'Would you like help?',
      intro_helper_text: 'Choose how to continue.',
      inputs: [{ input_id: 'amount', question: 'What deduction amount applies?', helper_text: null, answer_type: 'currency', options: [] }],
    },
  };
  const worksheetState = { ...state(0), question: worksheetQuestion, prior_answers: {} };
  vi.stubGlobal('fetch', vi.fn((url: string) => url.endsWith('/glossary') ? reply({ terms: [] }) : reply(worksheetState)));
  render(<GuidedConversation sessionId="s1" />);

  expect(await screen.findByRole('button', { name: /I already completed the worksheet/ })).toBeTruthy();
  expect(screen.getByRole('button', { name: /Help me work through the worksheet/ })).toBeTruthy();
  expect(screen.getByRole('button', { name: /leave this blank/ })).toBeTruthy();
  expect(screen.queryByLabelText('Type your answer')).toBeNull();
  expect(screen.getByText(worksheetQuestion.help_text)).toBeTruthy();
});

it('shows loading instead of original wording until Gemini finishes the current question', async () => {
  let polls = 0;
  const loading = { ...state(0), status: 'loading', question };
  const fetchMock = vi.fn((url: string) => {
    if (url.endsWith('/glossary')) return reply({ terms: [] });
    if (url.endsWith('/next-question')) {
      polls += 1;
      return reply(polls === 1 ? loading : state(0));
    }
    throw Error(`unexpected ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<GuidedConversation sessionId="s1" />);

  expect(await screen.findByText('Loading this question…')).toBeTruthy();
  expect(screen.queryByText(question.original_text)).toBeNull();
  expect(screen.queryByRole('textbox', { name: 'Type your answer' })).toBeNull();
  expect(await screen.findByText('How many children under 17?', {}, { timeout: 2000 })).toBeTruthy();
  expect(polls).toBeGreaterThanOrEqual(2);
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
 fireEvent.click(screen.getByRole('button',{name:'Conversation so far'}));
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
  act(() => calls.onMessage?.({ message: '[happy] How many children do you have?', source: 'ai' }));
  expect(screen.getByText('How many children do you have?')).toBeTruthy();
  act(() => calls.onMessage?.({ message: 'two', source: 'user' }));
  expect(screen.getByText('“two”')).toBeTruthy();
  act(() => calls.onMessage?.({ message: 'Got it.', source: 'ai' }));
  expect(screen.queryByText('“two”')).toBeNull();
});


it('flips the guide mascot and animates its mouth and tongue only during agent speech', async () => {
  calls.status = 'connected'; calls.speaking = true;
  let tick: FrameRequestCallback = () => {};
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => { tick = callback; return 1; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn(() => ({ matches: false })) });
  vi.stubGlobal('fetch', vi.fn((url: string) => url.endsWith('/glossary') ? reply({ terms: [] }) : reply(state(0))));
  const view = render(<GuidedConversation sessionId="s1" />);
  await screen.findByText('How many children under 17?');
  expect(view.container.querySelector('.guide-mascot .mascot-flipped')).toBeTruthy();
  act(() => tick(40));
  const tongue = view.container.querySelector('.mascot-tongue');
  expect(tongue).toBeTruthy();
  expect(Number(tongue?.getAttribute('ry'))).toBeGreaterThan(0);
  calls.speaking = false;
  view.rerender(<GuidedConversation sessionId="s1" />);
  expect(view.container.querySelector('.mascot-mouth')).toBeNull();
});

it('offers date entry during voice and tells the agent how to handle spoken dates',async()=>{
 calls.status='connected';
 const dateQuestion={...question,id:'birth',input_type:'date',simplified_question:'What is your birth date?'};
 vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/glossary')?reply({terms:[]}):url.endsWith('/sessions/s1')?reply({fields:[]}):reply({...state(0),question:dateQuestion})));
 render(<GuidedConversation sessionId="s1"/>);
 const date=await screen.findByLabelText('Date (month/day/year)');
 expect(calls.context.mock.calls.some(([text])=>text.includes('Accept spoken dates naturally'))).toBe(true);
 fireEvent.change(date,{target:{value:'2000-01-02'}});fireEvent.click(screen.getByRole('button',{name:'Use this date'}));
 expect(calls.send).toHaveBeenCalledWith('2000-01-02');expect(calls.start).not.toHaveBeenCalled();
});
