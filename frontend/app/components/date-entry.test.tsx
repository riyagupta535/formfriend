import {cleanup,render,screen,fireEvent} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import DateEntry from './date-entry';
afterEach(cleanup);
it('offers date entry without sending until the user chooses Use this date',()=>{
 const submit=vi.fn();render(<DateEntry busy={false} onSubmit={submit}/>);
 const button=screen.getByRole('button',{name:'Use this date'}) as HTMLButtonElement;
 expect(button.disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('Date (month/day/year)'),{target:{value:'2000-01-02'}});
 expect(submit).not.toHaveBeenCalled();fireEvent.click(button);
 expect(submit).toHaveBeenCalledWith('2000-01-02');
});
