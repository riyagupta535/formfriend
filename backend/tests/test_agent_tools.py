import json
import time
from pathlib import Path
import pytest
import pymupdf
from fastapi.testclient import TestClient
from app.main import app, sessions, documents
from app.agent_models import Validation
from app.models import CalculationSpec, FormField, Session, SubQuestion
from app.parser import extract_fields


def question(id, **overrides):
    return {'id':id,'original_text':id,'simplified_question':f'Please answer {id}?','input_type':'text',
            'depends_on':[],'show_if':None,'required':False,'pdf_field_name':None,**overrides}


def no_validation():
    return {
        'kind':'none','min':None,'max':None,
        'min_length':None,'max_length':None,'message':None,
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('AGENT_TOOL_SECRET', raising=False)
    before=set(sessions)
    with TestClient(app) as client:
        yield client
    for key in set(sessions)-before:
        sessions.pop(key,None);documents.pop(key,None)


def create(client, questions):
    response=client.post('/agent/sessions',json={'questions':questions})
    assert response.status_code==200,response.text
    return response.json()['session_id']


def answer(client,key,id,value,**extra):
    return client.post(f'/agent/sessions/{key}/answers',json={'question_id':id,'value':value,**extra})


def conditional_questions():
    return [question('spouse_employment',original_text='Complete this step if married filing jointly and your spouse also works.',
                     simplified_question='Does your spouse also work?',input_type='boolean',depends_on=['filing_status'],
                     show_if={'field':'filing_status','operator':'equals','value':'married_filing_jointly'}),
            question('filing_status',input_type='choice',options=['single','married_filing_jointly'],required=True)]


def test_exact_schema_missing_dependency_asked_first_and_false_is_saved(client):
    key=create(client,conditional_questions())
    initial=client.get(f'/agent/sessions/{key}/next-question').json()
    assert initial['question']['id']=='filing_status'
    assert initial['progress']['blocked']==1
    assert answer(client,key,'spouse_employment',True).status_code==409
    first=answer(client,key,'filing_status','married_filing_jointly',revision=0).json()
    assert first['next']['question']['id']=='spouse_employment'
    second=answer(client,key,'spouse_employment',False,raw_response='No, they do not.').json()
    assert second['value'] is False
    assert second['next']['status']=='complete'
    assert sessions[key][1].fields[0].user_response=='No'
    assert sessions[key][1].agent_state.raw_responses['spouse_employment']=='No, they do not.'
    assert not sessions[key][1].fields[0].confirmed


def test_false_condition_omitted_from_review_and_export(client):
    key=create(client,conditional_questions())
    result=answer(client,key,'filing_status','single').json()
    assert result['next']['status']=='complete'
    assert result['next']['progress']['not_applicable']==1
    review=client.get(f'/sessions/{key}').json()
    assert [f['field_id'] for f in review['fields']]==['filing_status']
    response=client.post(f'/sessions/{key}/review/export',json={'reviewed':True,'answers':[{'field_id':'filing_status','value':'single'}]})
    assert response.status_code==200,response.text
    with pymupdf.open(stream=response.content,filetype='pdf') as pdf:
        text=''.join(p.get_text() for p in pdf)
        assert 'single' in text
        assert 'spouse_employment' not in text


def test_changed_parent_invalidates_dependent_and_does_not_restore_old_answer(client):
    key=create(client,conditional_questions())
    answer(client,key,'filing_status','married_filing_jointly')
    answer(client,key,'spouse_employment',True)
    changed=answer(client,key,'filing_status','single').json()
    assert changed['invalidated_question_ids']==['spouse_employment']
    answer(client,key,'filing_status','married_filing_jointly')
    assert client.get(f'/agent/sessions/{key}/next-question').json()['question']['id']=='spouse_employment'
    assert sessions[key][1].fields[0].user_response is None


def test_skip_optional_and_reject_required_and_stale_updates(client):
    key=create(client,[question('name',required=True),question('nickname')])
    assert client.post(f'/agent/sessions/{key}/skip',json={'question_id':'name'}).status_code==422
    assert answer(client,key,'name','Alex',revision=0).status_code==200
    assert answer(client,key,'name','Sam',revision=0).status_code==409
    skipped=client.post(f'/agent/sessions/{key}/skip',json={'question_id':'nickname','revision':1})
    assert skipped.status_code==200
    assert skipped.json()['next']['status']=='complete'


def test_skipped_dependency_blocks_child_instead_of_guessing(client):
    key=create(client,[question('parent'),question('child',depends_on=['parent'])])
    result=client.post(f'/agent/sessions/{key}/skip',json={'question_id':'parent'}).json()
    assert result['next']['status']=='blocked'
    assert result['next']['blocked_question_ids']==['child']
    answer(client,key,'parent','Example')
    assert client.get(f'/agent/sessions/{key}/next-question').json()['question']['id']=='child'


@pytest.mark.parametrize('kind,bad,good',[('boolean','maybe',True),('number',True,42),('currency','about 500',500),
    ('date','March fifth','2000-03-05'),('choice','Other','A'),('multichoice',['Other'],['A']),('text','  ','Example')])
def test_typed_values_are_not_guessed(client,kind,bad,good):
    key=create(client,[question('value',input_type=kind,options=['A','B'] if 'choice' in kind else [])])
    assert answer(client,key,'value',bad).status_code==422
    assert client.get(f'/agent/sessions/{key}/next-question').json()['revision']==0
    assert answer(client,key,'value',good).status_code==200


@pytest.mark.parametrize('questions',[
    [question('duplicate'),question('duplicate')],
    [question('a',depends_on=['missing'])],
    [question('a',depends_on=['b']),question('b',depends_on=['a'])],
    [question('a',show_if={'field':'b','operator':'equals','value':'yes'}),question('b')],
    [question('a',input_type='choice')],
])
def test_invalid_question_graphs_rejected(client,questions):
    assert client.post('/agent/sessions',json={'questions':questions}).status_code==422


def test_context_preserves_original_and_dependency_values(client):
    key=create(client,conditional_questions())
    answer(client,key,'filing_status','married_filing_jointly')
    context=client.get(f'/agent/sessions/{key}/questions/spouse_employment/context').json()
    assert context['question']=={**conditional_questions()[0],'options':[],'help_text':'','validation':no_validation(),
                                 'source_reference':None,'key_terms':[]}
    assert context['dependency_answers']=={'filing_status':'married_filing_jointly'}
    assert context['source_page'] is None
    assert client.get(f'/agent/sessions/{key}/questions/missing/context').status_code==404


def test_pdf_mapping_preserves_native_widget_reference(client):
    with pymupdf.open() as doc:
        page=doc.new_page()
        widget=pymupdf.Widget();widget.field_name='full_name';widget.field_type=pymupdf.PDF_WIDGET_TYPE_TEXT
        widget.rect=pymupdf.Rect(40,50,300,80);page.add_widget(widget)
        data=doc.tobytes()
    fields=extract_fields(data)
    sessions['source-test']=(time.monotonic(),Session(session_id='source-test',filename='sample.pdf',mode='mock',fields=fields))
    documents['source-test']=data
    response=client.post('/agent/sessions',json={'document_session_id':'source-test','questions':[question('name',pdf_field_name='full_name')]})
    assert response.status_code==200,response.text
    key=response.json()['session_id']
    answer(client,key,'name','Alex Example')
    pdf=client.post(f'/sessions/{key}/review/export',json={'reviewed':True,'answers':[{'field_id':'name','value':'Alex Example'}]})
    assert pdf.status_code==200,pdf.text if pdf.status_code!=200 else ''
    with pymupdf.open(stream=pdf.content,filetype='pdf') as document:
        assert next(document[0].widgets()).field_value=='Alex Example'


def test_final_review_cannot_bypass_required_or_branching(client):
    key=create(client,conditional_questions())
    answer(client,key,'filing_status','single')
    assert client.post(f'/sessions/{key}/review/export',json={'reviewed':True,'answers':[{'field_id':'filing_status','value':''}]}).status_code==422
    assert client.post(f'/sessions/{key}/review/export',json={'reviewed':True,'answers':[{'field_id':'filing_status','value':'married_filing_jointly'}]}).status_code==409
    assert sessions[key][1].fields[1].user_response=='single'
    assert client.post(f'/sessions/{key}/fields/filing_status',json={'value':'single'}).status_code==409
    assert client.get(f'/sessions/{key}/export').status_code==409


def test_secret_auth_and_session_expiry(client,monkeypatch):
    key=create(client,[question('name')])
    monkeypatch.setenv('AGENT_TOOL_SECRET','test-only-secret')
    assert client.get(f'/agent/sessions/{key}/next-question').status_code==401
    assert client.get(f'/agent/sessions/{key}/next-question',headers={'Authorization':'Bearer test-only-secret'}).status_code==200
    sessions[key]=(time.monotonic()-3601,sessions[key][1])
    assert client.get(f'/agent/sessions/{key}/next-question',headers={'Authorization':'Bearer test-only-secret'}).status_code==404


def test_transitive_dependents_and_idempotent_answer(client):
    key=create(client,[question('parent'),question('child',depends_on=['parent']),question('grandchild',depends_on=['child'])])
    answer(client,key,'parent','A');answer(client,key,'child','B');answer(client,key,'grandchild','C')
    assert answer(client,key,'parent','A').json()['invalidated_question_ids']==[]
    result=answer(client,key,'parent','Changed').json()
    assert result['invalidated_question_ids']==['child','grandchild']
    assert result['next']['question']['id']=='child'
    assert result['next']['progress']['blocked']==1


def test_unmapped_pdf_question_uses_answer_sheet_instead_of_guessing(client):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40,40),'Synthetic original form')
        data=doc.tobytes()
    sessions['unmapped-source']=(time.monotonic(),Session(session_id='unmapped-source',filename='sample.pdf',mode='mock',fields=[]))
    documents['unmapped-source']=data
    response=client.post('/agent/sessions',json={'document_session_id':'unmapped-source','questions':[question('unmapped')]})
    key=response.json()['session_id']
    answer(client,key,'unmapped','Synthetic answer')
    response=client.post(f'/sessions/{key}/review/export',json={'reviewed':True,'answers':[{'field_id':'unmapped','value':'Synthetic answer'}]})
    assert response.status_code==200
    with pymupdf.open(stream=response.content,filetype='pdf') as pdf:
        assert len(pdf)==2
        assert 'Synthetic original form' in pdf[0].get_text()
        assert 'Synthetic answer' in pdf[1].get_text()
        assert 'source page not provided' in pdf[1].get_text()


def llm_question(**overrides):
    """The exact shape emitted by question generation."""
    return {'id':'agi','original_text':'Enter your adjusted gross income (AGI) from line 11.',
            'simplified_question':'How much was your total income after adjustments?',
            'help_text':'AGI is on line 11 of last year\'s Form 1040.','input_type':'currency','required':True,
            'depends_on':[],'show_if':None,'options':[],
            'validation':{'kind':'decimal_number','min':0,'message':'Income cannot be negative.'},
            'pdf_field_name':None,'source_reference':{'page':1,'section':'Step 2'},'key_terms':['adjusted gross income'],
            **overrides}


def test_accepts_full_llm_schema_and_exposes_hints(client):
    key=create(client,[llm_question()])
    question=client.get(f'/agent/sessions/{key}/next-question').json()['question']
    assert question['help_text'].startswith('AGI')
    assert question['source_reference']=={'page':1,'section':'Step 2'}
    assert question['key_terms']==['adjusted gross income']


def test_validation_rules_trigger_follow_up(client):
    key=create(client,[llm_question(),
                       question('zip',validation={'kind':'us_postal_code'}),
                       question('note')])
    rejected=answer(client,key,'agi',-5)
    assert rejected.status_code==422 and rejected.json()['detail']=='Income cannot be negative.'
    assert answer(client,key,'agi',52000).status_code==200
    assert answer(client,key,'zip','9002').status_code==422
    assert answer(client,key,'zip',' 90024 ').status_code==200
    assert answer(client,key,'note','anything').status_code==200


def test_unknown_validation_kind_rejected(client):
    response=client.post('/agent/sessions',json={'questions':[question('zip',validation={'kind':'made_up'})]})
    assert response.status_code==422


@pytest.mark.parametrize('kind,bad,good',[
    ('social_security_number','lkj','123-45-6789'),
    ('employer_identification_number','123456','12-3456789'),
    ('taxpayer_identification_number','not an id','12-3456789'),
    ('email','alex.example','alex@example.com'),
    ('phone_number','call me','(415) 555-1212'),
    ('us_postal_code','9021','90210-1234'),
    ('us_state_code','California','CA'),
    ('integer','2.5','2'),
    ('year','26','2026'),
])
def test_closed_validation_kinds_reject_bad_text_without_advancing(client,kind,bad,good):
    key=create(client,[question('value',validation={'kind':kind})])
    rejected=answer(client,key,'value',bad,revision=0)
    assert rejected.status_code==422
    current=client.get(f'/agent/sessions/{key}/next-question').json()
    assert current['revision']==0
    assert current['question']['id']=='value'
    assert answer(client,key,'value',good,revision=0).status_code==200


def test_explain_term_saves_agent_explanation_to_glossary(client):
    key=create(client,[llm_question()])
    before=client.get(f'/agent/sessions/{key}/next-question').json()['revision']
    body={'question_id':'agi','term':'Adjusted gross income ','explanation':'Your income minus some allowed costs.'}
    saved=client.post(f'/agent/sessions/{key}/explain',json=body).json()
    assert saved=={'saved':True,'term':'Adjusted gross income','glossary_size':1}
    # Re-explaining the same term (any case) replaces it with the newer, simpler wording.
    client.post(f'/agent/sessions/{key}/explain',json={**body,'term':'adjusted gross income','explanation':'Simpler.','example':'Pay minus costs.'})
    terms=client.get(f'/agent/sessions/{key}/glossary').json()['terms']
    assert [(t['term'],t['explanation'],t['example']) for t in terms]==[('adjusted gross income','Simpler.','Pay minus costs.')]
    assert client.get(f'/agent/sessions/{key}/next-question').json()['revision']==before


def test_explain_term_rejects_unknown_question_and_empty_text(client):
    key=create(client,[llm_question()])
    assert client.post(f'/agent/sessions/{key}/explain',json={'question_id':'missing','term':'x','explanation':'y'}).status_code==404
    assert client.post(f'/agent/sessions/{key}/explain',json={'question_id':'agi','term':'x','explanation':''}).status_code==422


def test_elevenlabs_client_tools_match_backend_routes():
    import re
    from app.elevenlabs_agent import PROMPT, tool_configs
    configs=[body['tool_config'] for body in tool_configs()]
    names={c['name'] for c in configs}
    assert names=={'get_next_question','save_answer','skip_question','get_question_context','explain_term'}
    operation_ids={op.get('operationId') for path in app.openapi()['paths'].values() for op in path.values()}
    assert names<=operation_ids
    for config in configs:
        assert config['type']=='client' and config['expects_response'] and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',config['name'])
        assert config['name'] in PROMPT
        params=config.get('parameters')
        if params:
            assert set(params['required'])<=set(params['properties'])
            # Session IDs and revisions are bound by the browser, never chosen by the model.
            assert not {'session_id','revision'}&set(params['properties'])


def upload_demo(client):
    with open(Path(__file__).resolve().parents[2]/'examples'/'demo-form.pdf','rb') as pdf:
        response=client.post('/sessions',files={'file':('demo-form.pdf',pdf,'application/pdf')})
    assert response.status_code==200,response.text
    return response.json()


def test_upload_becomes_guided_session_with_pdf_mapping_and_generated_rule(client, monkeypatch):
    monkeypatch.setattr('app.main.start_simplification', lambda _key: None)
    uploaded=upload_demo(client)
    source=sessions[uploaded['session_id']][1]
    source.simplification_status='complete'
    generated_name=next(field for field in source.fields if 'name' in field.original_question.lower())
    generated_name.validation=Validation(kind='person_name')
    created=client.post('/agent/sessions/from-upload',json={'document_session_id':uploaded['session_id']})
    assert created.status_code==200,created.text
    key=created.json()['session_id']
    assert uploaded['session_id'] not in sessions
    questions=sessions[key][1].agent_state.questions
    assert len(questions)==len(uploaded['fields'])
    assert all(q.pdf_field_name for q in questions)
    name=next(q for q in questions if 'name' in q.original_text.lower())
    assert answer(client,key,name.id,'1234').status_code==422
    assert answer(client,key,name.id,'Maria Lopez').status_code==200
    again=client.post('/agent/sessions/from-upload',json={'document_session_id':key})
    assert again.status_code==409


def test_upload_opens_guide_and_syncs_each_question_while_simplification_runs(client):
    field = FormField(
        field_id='name', original_question='1 Name', simplified_question='1 Name',
        source_page=1, source_rect=[], simplification_status='pending',
    )
    source = Session(
        session_id='pending-source', filename='form.pdf', mode='gemini',
        simplification_status='running', fields=[field],
    )
    sessions[source.session_id] = (time.monotonic(), source)
    documents[source.session_id] = b'%PDF-synthetic'

    response = client.post('/agent/sessions/from-upload', json={'document_session_id': source.session_id})

    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'loading'
    guided_id = response.json()['session_id']
    assert source.session_id in sessions

    field.simplified_question = 'What is your name?'
    field.helper_text = 'Enter your legal name.'
    field.validation = Validation(
        kind='person_name',
        message='Enter a name using letters, without numbers.',
    )
    field.subquestions = [
        SubQuestion(text='How many qualifying children do you have?', answer_type='number'),
    ]
    field.calculation = CalculationSpec(
        operation='multiply', input_question_indices=[0], factor=2200,
    )
    field.simplification_status = 'complete'
    field.simplification_confidence = 'high'
    source.simplification_status = 'complete'

    ready = client.get(f'/agent/sessions/{guided_id}/next-question')
    assert ready.status_code == 200
    assert ready.json()['status'] == 'question'
    assert ready.json()['question']['simplified_question'] == 'What is your name?'
    assert ready.json()['question']['validation']['kind'] == 'person_name'
    assert ready.json()['question']['subquestions'][0]['text'] == 'How many qualifying children do you have?'
    assert ready.json()['question']['calculation']['factor'] == 2200
    assert ready.json()['prior_answers'] == {'name': ''}
    rejected = answer(client, guided_id, 'name', '1234', revision=0)
    assert rejected.status_code == 422
    assert rejected.json()['detail'] == 'Enter a name using letters, without numbers.'
    assert client.get(f'/agent/sessions/{guided_id}/next-question').json()['revision'] == 0
    assert source.session_id not in sessions
