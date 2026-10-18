import {render,screen,fireEvent,cleanup} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import AnswerInput from './answer-input';
afterEach(cleanup);
it('shows saved ISO dates in month/day/year format and preserves edited text',()=>{
 const change=vi.fn(),blur=vi.fn();
 const {rerender}=render(<AnswerInput field={{answer_type:'date'}} id="dob" value="2000-01-02" onChange={change} onBlur={blur}/>);
 const input=screen.getByPlaceholderText('MM/DD/YYYY') as HTMLInputElement;
 expect(input.value).toBe('01/02/2000');
 fireEvent.change(input,{target:{value:'10/17/2026'}});expect(change).toHaveBeenCalledWith('10/17/2026');
 rerender(<AnswerInput field={{answer_type:'date'}} id="dob" value="10/17/2026" onChange={change} onBlur={blur}/>);
 fireEvent.blur(input);expect(blur).toHaveBeenCalledWith('10/17/2026');
});
