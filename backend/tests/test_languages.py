import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import languages, agent_tools, teaching, answer_judge
from app.main import app, sessions, documents
from app.models import FormField, Session
from app.dates import normalize_date


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('AGENT_TOOL_SECRET', raising=False)
    before = set(sessions)
    with TestClient(app) as client:
        yield client
    for key in set(sessions) - before:
        sessions.pop(key, None)
        documents.pop(key, None)


@pytest.fixture
def spanish(monkeypatch):
    calls = []
    async def translate(strings, language='es'):
        calls.append(strings)
        known = {'What is your name?': '¿Cómo te llamas?', 'Full name': '¿Cómo te llamas?', 'Choose your status': 'Elige tu estado civil',
                 'Single': 'Soltero', 'Married': 'Casado', 'Yes': 'Sí', 'No': 'No'}
        return {text: known.get(text, f'Español: {text}') for text in strings}
    monkeypatch.setattr(languages, 'translate_strings', translate)
    return calls


def create(client, **overrides):
    question = dict(id='name', original_text='Full legal name', simplified_question='What is your name?',
                    input_type='text')
    question.update(overrides)
    response = client.post('/agent/sessions', json={'language': 'es', 'questions': [question]})
    assert response.status_code == 200, response.text
    return response.json()


def test_spanish_display_and_review_preserve_original_form_and_answers(client, spanish):
    state = create(client)
    key = state['session_id']
    assert state['language'] == 'es'
    assert state['question']['simplified_question'] == '¿Cómo te llamas?'
    assert state['question']['original_text'] == 'Full legal name'
    client.get(f'/agent/sessions/{key}/next-question')
    assert len(spanish) == 1  # session cache avoids repeated translation requests
    saved = client.post(f'/agent/sessions/{key}/answers', json={
        'question_id': 'name', 'value': 'María López', 'raw_response': 'María López', 'revision': 0,
    })
    assert saved.json()['saved']
    review = client.get(f'/sessions/{key}').json()
    assert review['language'] == 'es'
    assert review['fields'][0]['simplified_question'] == '¿Cómo te llamas?'
    assert review['fields'][0]['original_question'] == 'Full legal name'
    assert review['fields'][0]['user_response'] == 'María López'
    assert sessions[key][1].fields[0].simplified_question == 'What is your name?'
    assert '_question_presentations' not in review


def test_spanish_choices_keep_canonical_values_for_export(client, spanish):
    state = create(client, input_type='choice', options=['Single', 'Married'])
    question = state['question']
    assert question['options'] == ['Single', 'Married']
    assert question['option_labels']['Single'] == 'Soltero'
    key = state['session_id']
    saved = client.post(f'/agent/sessions/{key}/answers', json={'question_id': 'name', 'value': 'Single'})
    assert saved.json()['value'] == 'Single'
    assert client.get(f'/sessions/{key}').json()['fields'][0]['option_labels']['Single'] == 'Soltero'


def test_spanish_validation_reasks_without_saving_or_advancing(client, spanish):
    state = create(client, validation={'kind': 'person_name'})
    key = state['session_id']
    response = client.post(f'/agent/sessions/{key}/answers', json={'question_id': 'name', 'value': '123'})
    assert response.status_code == 422
    assert response.json()['detail'].startswith('Español:')
    assert client.get(f'/agent/sessions/{key}/next-question').json()['revision'] == 0
    assert sessions[key][1].fields[0].user_response is None


def test_upload_bridge_inherits_language(client, spanish):
    source = Session(session_id='spanish-upload', filename='form.pdf', language='es', mode='mock',
                     fields=[FormField(field_id='name', original_question='Full name',
                                       simplified_question='What is your name?', source_page=1, source_rect=[])])
    sessions[source.session_id] = (time.monotonic(), source)
    documents[source.session_id] = b'%PDF-synthetic'
    response = client.post('/agent/sessions/from-upload', json={'document_session_id': source.session_id})
    assert response.status_code == 200, response.text
    assert response.json()['language'] == 'es'
    assert client.get(f"/sessions/{response.json()['session_id']}").json()['language'] == 'es'


def test_translation_failure_is_visible_and_does_not_drop_question(client, monkeypatch):
    async def unavailable(strings, language='es'):
        raise RuntimeError('secret provider detail')
    monkeypatch.setattr(languages, 'translate_strings', unavailable)
    state = create(client, validation={'kind': 'person_name'})
    assert state['question']['simplified_question'] == 'What is your name?'
    assert 'unavailable' in state['language_notice']
    assert 'secret' not in json.dumps(state)
    response = client.post(f"/agent/sessions/{state['session_id']}/answers", json={'question_id': 'name', 'value': '123'})
    assert response.status_code == 422
    assert response.json()['detail'].startswith('La respuesta')


def test_unsupported_language_rejected(client):
    response = client.post('/agent/sessions', json={'language': 'xx', 'questions': [{
        'id': 'x', 'original_text': 'Name', 'simplified_question': 'Name?', 'input_type': 'text',
    }]})
    assert response.status_code == 422
    response = client.post('/sessions', data={'language': 'xx'}, files={'file': ('x.pdf', b'%PDF-fake')})
    assert response.status_code == 422


async def check_translation_preserves_rules_references_and_original_text(monkeypatch):
    async def fake(system, request, **kwargs):
        assert 'Spanish' in system
        data = json.loads(request)
        return json.dumps({key: 'Traducido: ' + text for key, text in data.items()})
    monkeypatch.setattr(languages, 'gemini_json', fake)
    session = Session(session_id='x', filename='x', mode='mock', fields=[], language='es')
    question = {'id': 'income', 'simplified_question': 'How much?', 'original_text': 'Amount in dollars',
                'options': ['Single'], 'calculation': {'operation': 'multiply', 'factor': 2000,
                'source_field_ids': ['children'], 'condition_answer': 'Single'},
                'decision_tree': {'nodes': [{'node_id': 'n', 'question': 'Married?',
                                            'answers': [{'label': 'Yes', 'terminal_option': 'Single'}]}]}}
    result = await languages.present_question(session, question)
    assert result['simplified_question'] == 'Traducido: How much?'
    assert result['original_text'] == question['original_text']
    assert result['calculation'] == question['calculation']
    assert result['options'] == ['Single']
    assert result['decision_tree']['nodes'][0]['answers'][0]['terminal_option'] == 'Single'
    assert result['decision_tree']['nodes'][0]['answers'][0]['label'] == 'Traducido: Yes'
    assert question['simplified_question'] == 'How much?'
    changed = await languages.present_question(session, {**question, 'simplified_question': 'Updated question'})
    assert changed['simplified_question'] == 'Traducido: Updated question'


async def check_teaching_and_answer_judge_request_spanish(monkeypatch):
    from app.agent_models import AgentQuestion
    question = AgentQuestion(id='tax', original_text='Exempt', simplified_question='Are you exempt?', input_type='text')
    async def lesson(system, request, **kwargs):
        assert 'Spanish' in system
        assert json.loads(request)['response_language'] == 'Spanish'
        return json.dumps({'needed': True, 'title': 'Qué significa exento', 'explanation': 'No se retienen ciertos impuestos.'})
    monkeypatch.setattr(teaching, 'gemini_json', lesson)
    result = await teaching.lesson_for(question, '¿Qué significa?', language='es')
    assert result.trigger == 'asked'
    assert result.title == 'Qué significa exento'
    async def judge(system, request, **kwargs):
        assert 'Spanish' in system
        return json.dumps({'reasoning': 'They asked for help', 'verdict': 'help', 'help_topic': 'exento'})
    monkeypatch.setattr(answer_judge, 'gemini_json', judge)
    assert (await answer_judge.judge_answer(question, '¿Qué significa exento?', '¿Qué significa exento?', {}, language='es')).verdict == 'help'


@pytest.mark.parametrize('value,expected', [('2 de enero de 2000', '2000-01-02'), ('15 marzo 2024', '2024-03-15')])
def test_spanish_named_dates(value, expected):
    assert normalize_date(value) == expected


def test_translation_preserves_rules_references_and_original_text(monkeypatch):
    asyncio.run(check_translation_preserves_rules_references_and_original_text(monkeypatch))


def test_teaching_and_answer_judge_request_spanish(monkeypatch):
    asyncio.run(check_teaching_and_answer_judge_request_spanish(monkeypatch))


def test_spanish_review_validation_is_localized_and_atomic(client, spanish):
    state = create(client, validation={'kind': 'person_name'})
    key = state['session_id']
    response = client.post(f'/sessions/{key}/review/export', json={
        'reviewed': True, 'answers': [{'field_id': 'name', 'value': '123'}],
    })
    assert response.status_code == 422
    assert response.json()['detail'].startswith('Español:')
    assert sessions[key][1].fields[0].user_response is None


def test_enable_language_selection_preserves_other_agent_settings():
    from importlib.util import spec_from_file_location, module_from_spec
    from pathlib import Path
    from copy import deepcopy
    import httpx
    path = Path(__file__).resolve().parents[1] / 'scripts/setup_elevenlabs_agent.py'
    spec = spec_from_file_location('agent_setup', path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    current = {'conversation_config': {'agent': {'prompt': {'prompt': 'Keep this prompt'}}},
               'platform_settings': {'overrides': {'conversation_config_override': {
                   'agent': {'first_message': True, 'prompt': {'prompt': False}},
                   'tts': {'voice_id': False}}, 'some_other_setting': True}}}
    patches = []
    def handle(request):
        if request.method == 'GET':
            return httpx.Response(200, json=current)
        patches.append(json.loads(request.content))
        return httpx.Response(200, json={})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert module.enable_language_selection(client, 'demo')
    expected = deepcopy(current['platform_settings']['overrides'])
    expected['conversation_config_override']['agent']['language'] = True
    assert patches == [{'platform_settings': {'overrides': expected}}]


def test_language_can_be_selected_after_parsing_without_reparsing(client, spanish):
    source = Session(session_id='choose-after-upload', filename='form.pdf', mode='mock',
                     fields=[FormField(field_id='name', original_question='Full name',
                                       simplified_question='What is your name?', source_page=1, source_rect=[])])
    sessions[source.session_id] = (time.monotonic(), source)
    documents[source.session_id] = b'%PDF-original'
    response = client.post(f'/sessions/{source.session_id}/language', json={'language': 'es'})
    assert response.status_code == 200
    assert response.json() == {'session_id': source.session_id, 'language': 'es'}
    assert documents[source.session_id] == b'%PDF-original'
    assert source.fields[0].original_question == 'Full name'
    assert spanish == []  # language selection does not invoke translation or OCR
    guided = client.post('/agent/sessions/from-upload', json={'document_session_id': source.session_id})
    assert guided.json()['language'] == 'es'
    assert guided.json()['question']['simplified_question'] == '¿Cómo te llamas?'


def test_language_selection_rejects_unsupported_languages_and_mid_conversation_changes(client, spanish):
    state = create(client)
    key = state['session_id']
    assert client.post(f'/sessions/{key}/language', json={'language': 'xx'}).status_code == 422
    assert client.post(f'/agent/sessions/{key}/answers', json={'question_id': 'name', 'value': 'María López'}).status_code == 200
    assert client.post(f'/sessions/{key}/language', json={'language': 'en'}).status_code == 409
    assert sessions[key][1].language == 'es'
    assert sessions[key][1].fields[0].user_response == 'María López'
    assert client.post('/sessions/missing/language', json={'language': 'es'}).status_code == 404


@pytest.mark.parametrize('language', ['en', 'es', 'zh', 'fil', 'vi', 'ar', 'fr', 'ko', 'pt', 'hi'])
def test_all_languages_present_questions_and_review_without_changing_saved_values(client, monkeypatch, language):
    calls = []
    async def translate(strings, target):
        calls.append(target)
        return {text: f'{target}: {text}' for text in strings}
    monkeypatch.setattr(languages, 'translate_strings', translate)
    created = client.post('/agent/sessions', json={'language': language, 'questions': [{
        'id': 'status', 'original_text': 'Marital status', 'simplified_question': 'Choose your status',
        'input_type': 'choice', 'options': ['Single', 'Married'],
    }]})
    assert created.status_code == 200, created.text
    state = created.json()
    key = state['session_id']
    assert state.get('language', 'en') == language
    assert state['question']['options'] == ['Single', 'Married']
    assert state['question']['original_text'] == 'Marital status'
    if language != 'en':
        assert state['question']['simplified_question'] == f'{language}: Choose your status'
        assert state['question']['option_labels']['Single'] == f'{language}: Single'
        assert calls == [language]
    else:
        assert calls == []
    assert client.post(f'/agent/sessions/{key}/answers', json={'question_id': 'status', 'value': 'Single'}).json()['saved']
    review = client.get(f'/sessions/{key}').json()
    assert review['language'] == language
    assert review['fields'][0]['user_response'] == 'Single'
    if language != 'en':
        assert review['fields'][0]['option_labels']['Single'] == f'{language}: Single'


@pytest.mark.parametrize('language', ['es', 'zh', 'fil', 'vi', 'ar', 'fr', 'ko', 'pt', 'hi'])
def test_localized_feedback_survives_translation_provider_failure(client, monkeypatch, language):
    async def broken(*args, **kwargs):
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr(languages, 'translate_strings', broken)
    created = client.post('/agent/sessions', json={'language': language, 'questions': [{
        'id': 'name', 'original_text': 'Full name', 'simplified_question': 'What is your name?',
        'input_type': 'text', 'validation': {'kind': 'person_name'},
    }]}).json()
    key = created['session_id']
    assert languages.LANGUAGE_NAMES[language] in created['language_notice']
    rejected = client.post(f'/agent/sessions/{key}/answers', json={'question_id': 'name', 'value': '123'})
    assert rejected.status_code == 422
    assert rejected.json()['detail'] == languages.ANSWER_ERRORS[language]
    assert sessions[key][1].agent_state.revision == 0


@pytest.mark.parametrize('language', ['es', 'zh', 'fil', 'vi', 'ar', 'fr', 'ko', 'pt', 'hi'])
def test_translator_teacher_and_judge_use_the_selected_language(monkeypatch, language):
    from app.agent_models import AgentQuestion
    question = AgentQuestion(id='name', original_text='Name', simplified_question='Your name?', input_type='text')
    target = languages.LANGUAGE_INSTRUCTIONS[language]
    async def run():
        async def translation(system, request, **kwargs):
            assert target in system
            assert kwargs['purpose'] == f'question-{language}-v2'
            return json.dumps({key: f'{language}: {value}' for key, value in json.loads(request).items()})
        monkeypatch.setattr(languages, 'gemini_json', translation)
        assert (await languages.translate_strings(['Your name?'], language))['Your name?'] == f'{language}: Your name?'
        async def lesson(system, request, **kwargs):
            assert target in system
            assert json.loads(request)['response_language'] == languages.LANGUAGE_NAMES[language]
            return json.dumps({'needed': True, 'title': 'Lesson', 'explanation': 'Explanation'})
        monkeypatch.setattr(teaching, 'gemini_json', lesson)
        assert (await teaching.lesson_for(question, 'Help', language=language)).needed
        async def judge(system, request, **kwargs):
            assert target in system
            return json.dumps({'reasoning': 'Wrong answer', 'verdict': 'reask', 'message': ''})
        monkeypatch.setattr(answer_judge, 'gemini_json', judge)
        assert (await answer_judge.judge_answer(question, '123', '123', {}, language=language)).message == languages.REASK_MESSAGES[language]
    asyncio.run(run())


def test_us_address_validation_accepts_city_names_in_other_scripts(client):
    key = client.post('/agent/sessions', json={'questions': [{
        'id': 'city', 'original_text': 'City, state, ZIP code', 'simplified_question': 'City, state, ZIP?',
        'input_type': 'text', 'validation': {'kind': 'city_state_zip'},
    }]}).json()['session_id']
    response = client.post(f'/agent/sessions/{key}/answers', json={
        'question_id': 'city', 'value': 'لوس أنجلوس، CA 90024',
    })
    assert response.status_code == 200
    assert response.json()['value'] == 'لوس أنجلوس، CA 90024'
