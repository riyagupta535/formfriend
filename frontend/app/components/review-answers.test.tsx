import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ReviewAnswers from './review-answers';
const session = {session_id:'review',filename:'sample.pdf',document_type:'pdf',fields:[
  {field_id:'name',original_question:'Full name',simplified_question:'Your name?',source_page:1,user_response:'Old Example'},
  {field_id:'city',original_question:'City',simplified_question:'Your city?',source_page:1,user_response:null},
]};
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('requires review and resets that approval after an edit without saving on blur',()=>{
  const fetchMock=vi.fn();vi.stubGlobal('fetch',fetchMock);
  render(<ReviewAnswers session={session} onClear={vi.fn()}/>);
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
