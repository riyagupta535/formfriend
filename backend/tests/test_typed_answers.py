import pytest
from fastapi.testclient import TestClient
from app.main import app, sessions, documents
from app.typed_answers import Interpretation


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.delenv('AGENT_TOOL_SECRET', raising=False)
    with TestClient(app) as client:
        response=client.post('/agent/sessions',json={'questions':[{
            'id':'name','original_text':'First name','simplified_question':'What is your first name?',
            'input_type':'text','validation':{'pattern':r'[^\d]+','message':'Names cannot contain numbers.'}}]})
        key=response.json()['session_id']
        yield client,key
        sessions.pop(key,None);documents.pop(key,None)


def submit(client,key,text='Riya',revision=0):
    return client.post(f'/agent/sessions/{key}/typed-answers',json={'question_id':'name','text':text,'revision':revision})


def test_unclear_text_and_questions_never_advance(setup,monkeypatch):
    client,key=setup
    async def clarify(*args):return Interpretation(action='clarify',reply='Could you type your first name?')
    monkeypatch.setattr('app.typed_answers.interpret_reply',clarify)
    result=submit(client,key,'asdfgh').json()
    assert not result['saved'] and result['next']['revision']==0
    assert result['next']['progress']['answered']==0
    async def explain(*args):return Interpretation(action='explain',reply='Use the name you go by. What is your first name?')
    monkeypatch.setattr('app.typed_answers.interpret_reply',explain)
    assert submit(client,key,'What does first name mean?').json()['saved'] is False
    assert sessions[key][1].fields[0].user_response is None


def test_clear_typed_answer_uses_shared_validation_and_save(setup,monkeypatch):
    client,key=setup
    async def accept(*args):return Interpretation(action='save',value='Riya',reply='Thanks.')
    monkeypatch.setattr('app.typed_answers.interpret_reply',accept)
    result=submit(client,key).json()
    assert result['saved'] and result['next']['status']=='complete'
    assert sessions[key][1].fields[0].user_response=='Riya'


def test_provider_cannot_override_rules(setup,monkeypatch):
    client,key=setup
    async def invalid(*args):return Interpretation(action='save',value='1234',reply='Thanks.')
    monkeypatch.setattr('app.typed_answers.interpret_reply',invalid)
    assert submit(client,key,'1234').status_code==422
    assert sessions[key][1].agent_state.revision==0


def test_validation_failure_does_not_silently_save(setup,monkeypatch):
    client,key=setup
    async def unavailable(*args):raise RuntimeError('private provider error')
    monkeypatch.setattr('app.typed_answers.interpret_reply',unavailable)
    response=submit(client,key)
    assert response.status_code==503 and 'private provider' not in response.text
    assert sessions[key][1].agent_state.revision==0


def test_progress_change_during_check_rejects_stale_answer(setup,monkeypatch):
    client,key=setup
    async def race(*args):
        sessions[key][1].agent_state.revision+=1
        return Interpretation(action='save',value='Riya',reply='Thanks.')
    monkeypatch.setattr('app.typed_answers.interpret_reply',race)
    assert submit(client,key).status_code==409
    assert sessions[key][1].fields[0].user_response is None
