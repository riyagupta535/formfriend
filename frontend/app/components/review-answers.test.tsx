import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ReviewAnswers from './review-answers';
const session = {session_id:'review',filename:'sample.pdf',document_type:'pdf',fields:[
  {field_id:'name',original_question:'(a) Full name',simplified_question:'Your name?',source_page:1,user_response:'Old Example'},
  {field_id:'city',original_question:'1 City',simplified_question:'Your city?',source_page:1,user_response:null},
]};
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('removes form line and part prefixes from original review questions',()=>{
  const childCredit = 'Step 3: Multiply the number of qualifying children under age 17 by $2,200 3(a) $ and Other.';
  const otherCredit = 'Multiply the number of other dependents by $500 3(b) $ Credits';
  const otherIncome = 'Step 4: (a) Other income (not from jobs). If you want tax withheld for other income you expect this year that won’t have withholding, enter the amount of other income here Other This may include interest, dividends, and retirement income 4(a) $ Adjustments';
  render(<ReviewAnswers session={{...session,fields:[
    {...session.fields[0],field_id:'jobs',original_question:'1 Two jobs'},
    {...session.fields[1],field_id:'lookup',original_question:'a Find the amount from the table'},
    {...session.fields[1],field_id:'lookup-2a',original_question:'2a Enter the table amount'},
    {...session.fields[1],field_id:'child-credit',original_question:childCredit},
    {...session.fields[1],field_id:'other-credit',original_question:otherCredit},
    {...session.fields[1],field_id:'other-income',original_question:otherIncome},
  ]}} onClear={vi.fn()}/>);
  expect(screen.getByText('Two jobs')).toBeTruthy();
  expect(screen.getByText('Find the amount from the table')).toBeTruthy();
  expect(screen.getByText('Enter the table amount')).toBeTruthy();
  expect(screen.queryByText('1 Two jobs')).toBeNull();
  expect(screen.queryByText('a Find the amount from the table')).toBeNull();
  expect(screen.queryByText('2a Enter the table amount')).toBeNull();
  expect(screen.getByText('Step 3: Multiply the number of qualifying children under age 17 by $2,200')).toBeTruthy();
  expect(screen.getByText('Multiply the number of other dependents by $500')).toBeTruthy();
  expect(screen.getByText('Step 4: Other income (not from jobs). If you want tax withheld for other income you expect this year that won’t have withholding, enter the amount of other income here. This may include interest, dividends, and retirement income')).toBeTruthy();
  expect(screen.queryByText(childCredit)).toBeNull();
  expect(screen.queryByText(otherCredit)).toBeNull();
  expect(screen.queryByText(otherIncome)).toBeNull();
});
it('requires review and resets that approval after an edit without saving on blur',()=>{
  const fetchMock=vi.fn();vi.stubGlobal('fetch',fetchMock);
  render(<ReviewAnswers session={session} onClear={vi.fn()}/>);
  expect(screen.queryByText('ONE LAST LOOK, AT YOUR PACE')).toBeNull();
  expect(screen.getByText('Full name')).toBeTruthy();
  expect(screen.getByText('City')).toBeTruthy();
  expect(screen.queryByText('(a) Full name')).toBeNull();
  expect(screen.queryByText('1 City')).toBeNull();
  expect(screen.queryByText('Your name?')).toBeNull();
  expect(screen.queryByText('Your city?')).toBeNull();
  expect(screen.queryByText(/Source page/)).toBeNull();
  expect(screen.getByText('No answer provided')).toBeTruthy();
  expect(screen.getByRole('region',{name:'Form answers'}).getAttribute('tabindex')).toBe('0');
  const download=screen.getByRole('button',{name:'Download PDF'});
  expect((download as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/1 answer is still blank/)).toBeTruthy();
  fireEvent.click(screen.getByRole('checkbox'));
  expect((download as HTMLButtonElement).disabled).toBe(false);
  fireEvent.change(screen.getByLabelText(/Full name/),{target:{value:'New Example'}});
  fireEvent.blur(screen.getByLabelText(/Full name/));
  expect((download as HTMLButtonElement).disabled).toBe(true);
  expect(fetchMock).not.toHaveBeenCalled();
});
it('exports the exact latest edits in one request as a PDF',async()=>{
  const fetchMock=vi.fn().mockResolvedValue({ok:true,blob:async()=>new Blob(['%PDF-test'],{type:'application/pdf'})});
  vi.stubGlobal('fetch',fetchMock);
  URL.createObjectURL=vi.fn().mockReturnValue('blob:pdf');URL.revokeObjectURL=vi.fn();
  const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  render(<ReviewAnswers session={session} onClear={vi.fn()}/>);
  fireEvent.change(screen.getByLabelText(/Full name/),{target:{value:'Latest Example'}});
  fireEvent.change(screen.getByLabelText(/City/),{target:{value:'Demo City'}});
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button',{name:'Download PDF'}));
  await screen.findByText(/PDF download has started/);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url,options]=fetchMock.mock.calls[0];
  expect(url).toContain('/sessions/review/review/export');
  expect(JSON.parse(options.body)).toEqual({reviewed:true,answers:[{field_id:'name',value:'Latest Example'},{field_id:'city',value:'Demo City'}]});
  expect(click).toHaveBeenCalledOnce();
});
it('keeps edits after an export failure so it can be retried',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,json:async()=>({detail:'PDF creation failed. Try again.'})}));
  render(<ReviewAnswers session={{...session,document_type:'image'}} onClear={vi.fn()}/>);
  expect(screen.getByText(/original document will not be filled/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText(/Full name/),{target:{value:'Keep this edit'}});
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button',{name:'Download PDF'}));
  await screen.findByRole('alert');
  expect((screen.getByLabelText(/Full name/) as HTMLTextAreaElement).value).toBe('Keep this edit');
  await waitFor(()=>expect((screen.getByRole('button',{name:'Download PDF'}) as HTMLButtonElement).disabled).toBe(false));
});

it('reviews Spanish question and choice labels while retaining canonical export values', () => {
  render(<ReviewAnswers session={{ ...session, language: 'es', fields: [{
    field_id: 'status', original_question: 'Filing status', simplified_question: '¿Cuál es tu estado civil?',
    source_page: 1, user_response: 'Single', answer_type: 'choice', options: ['Single', 'Married'],
    option_labels: { Single: 'Soltero', Married: 'Casado' },
  }] }} onClear={vi.fn()} />);
  const input = screen.getByRole('combobox', { name: /¿Cuál es tu estado civil/ }) as HTMLSelectElement;
  expect(input.value).toBe('Single');
  expect(screen.getByRole('option', { name: 'Soltero' }).getAttribute('value')).toBe('Single');
  fireEvent.change(input, { target: { value: 'Married' } });
  expect(input.value).toBe('Married');
  expect(screen.getByRole('button', { name: /Download PDF/ })).toBeTruthy();
});
