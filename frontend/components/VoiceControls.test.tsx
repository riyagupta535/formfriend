import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import VoiceControls from './VoiceControls';
class Mic {
 static current:Mic;
 onresult:((e:unknown)=>void)|null=null; onerror:((e:unknown)=>void)|null=null; onend:(()=>void)|null=null;
 start=vi.fn(); stop=vi.fn(); abort=vi.fn();
 constructor(){Mic.current=this;}
}
const props={question:'Your name?',fieldId:'name',answer:'',onAnswer:vi.fn()};
beforeEach(()=>{Object.defineProperty(window,'SpeechRecognition',{value:Mic,configurable:true});props.onAnswer=vi.fn();});
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();});
it('returns a transcript for editing without saving it',()=>{
 render(<VoiceControls {...props}/>);fireEvent.click(screen.getByText('Answer with microphone'));
 expect(Mic.current.start).toHaveBeenCalled();
 act(()=>Mic.current.onresult?.({results:[[{transcript:'Alex Example'}]]}));
 expect(props.onAnswer).toHaveBeenCalledWith('Alex Example');
 expect(screen.getByRole('status').textContent).toBe('Check your answer');
});
it('discards late transcripts after a field change',()=>{
 const view=render(<VoiceControls {...props}/>);fireEvent.click(screen.getByText('Answer with microphone'));const old=Mic.current;
 view.rerender(<VoiceControls {...props} fieldId="city" question="Your city?"/>);
 act(()=>old.onresult?.({results:[[{transcript:'stale answer'}]]}));
 expect(old.abort).toHaveBeenCalled();expect(props.onAnswer).not.toHaveBeenCalled();
});
it('uses the latest edited answer when dictation finishes',()=>{
 const view=render(<VoiceControls {...props}/>);fireEvent.click(screen.getByText('Answer with microphone'));
 view.rerender(<VoiceControls {...props} answer="Edited"/>);
 act(()=>Mic.current.onresult?.({results:[[{transcript:'more'}]]}));
 expect(props.onAnswer).toHaveBeenCalledWith('Edited more');
});
it('handles microphone denial and unsupported browsers',()=>{
 const view=render(<VoiceControls {...props}/>);fireEvent.click(screen.getByText('Answer with microphone'));
 act(()=>Mic.current.onerror?.({error:'not-allowed'}));expect(screen.getByRole('alert').textContent).toContain('permission was denied');
 view.unmount();Object.defineProperty(window,'SpeechRecognition',{value:undefined,configurable:true});render(<VoiceControls {...props}/>);
 expect((screen.getByText('Answer with microphone') as HTMLButtonElement).disabled).toBe(true);
});
it('shows the server message when audio is unconfigured',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,json:async()=>({detail:'Voice is not configured.'})}));
 render(<VoiceControls {...props}/>);fireEvent.click(screen.getByText('Read question aloud'));
 await waitFor(()=>expect(screen.getByRole('alert').textContent).toContain('not configured'));
});
it('stops microphone capture before speaking and releases audio on mute',async()=>{
 const pause=vi.fn(),play=vi.fn().mockResolvedValue(undefined);
 vi.stubGlobal('Audio',class {pause=pause;play=play;onended=null;onerror=null;});
 URL.createObjectURL=vi.fn().mockReturnValue('blob:test');URL.revokeObjectURL=vi.fn();
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,blob:async()=>new Blob(['audio'])}));
 render(<VoiceControls {...props}/>);fireEvent.click(screen.getByText('Answer with microphone'));const mic=Mic.current;
 fireEvent.click(screen.getByText('Read question aloud'));
 await waitFor(()=>expect(play).toHaveBeenCalled());expect(mic.abort).toHaveBeenCalled();
 fireEvent.click(screen.getByText('Mute voice'));expect(pause).toHaveBeenCalled();expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');
});
