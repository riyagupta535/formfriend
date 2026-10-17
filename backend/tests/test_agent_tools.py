import json
import time
import pytest
import pymupdf
from fastapi.testclient import TestClient
from app.main import app, sessions, documents
from app.models import Session
from app.parser import extract_fields


def question(id, **overrides):
    return {'id':id,'original_text':id,'simplified_question':f'Please answer {id}?','input_type':'text',
            'depends_on':[],'show_if':None,'required':False,'pdf_field_name':None,**overrides}


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
    assert context['question']=={**conditional_questions()[0],'options':[]}
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
