import time
import unicodedata
import pymupdf
import pytest
from fastapi.testclient import TestClient
from app.main import app, sessions, documents
from app.models import FormField, Session
from app.parser import extract_fields


@pytest.fixture
def review_session():
    with pymupdf.open() as doc:
        page = doc.new_page()
        widget = pymupdf.Widget()
        widget.field_name = 'Full name'
        widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        widget.rect = pymupdf.Rect(40, 70, 300, 100)
        page.add_widget(widget)
        data = doc.tobytes()
    fields = extract_fields(data)
    key = 'review-test'
    session = Session(session_id=key, filename='sample.pdf', mode='mock', fields=fields)
    sessions[key] = (time.monotonic(), session)
    documents[key] = data
    with TestClient(app) as client:
        yield client, session
    sessions.pop(key, None)
    documents.pop(key, None)


def post(client, session, value='Edited Example', **kwargs):
    return client.post('/sessions/review-test/review/export', json={
        'reviewed': True, 'answers': [{'field_id': session.fields[0].field_id, 'value': value}], **kwargs})


def test_reviewed_snapshot_fills_pdf_and_saves_answers(review_session):
    client, session = review_session
    response = post(client, session)
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['cache-control'] == 'no-store'
    assert '.pdf' in response.headers['content-disposition']
    with pymupdf.open(stream=response.content, filetype='pdf') as pdf:
        assert next(pdf[0].widgets()).field_value == 'Edited Example'
    saved = sessions['review-test'][1].fields[0]
    assert saved.user_response == 'Edited Example'
    assert saved.confirmed


def test_confirmation_and_complete_field_mapping_required(review_session):
    client, session = review_session
    assert post(client, session, reviewed=False).status_code == 422
    assert post(client, session, answers=[]).status_code == 422
    row = {'field_id':session.fields[0].field_id,'value':'Example'}
    assert post(client, session, answers=[row, row]).status_code == 422
    assert session.fields[0].user_response is None


def test_failed_export_does_not_partially_save(review_session, monkeypatch):
    client, session = review_session
    def fail(*args):
        raise RuntimeError('private internal details')
    monkeypatch.setattr('app.review.reviewed_pdf', fail)
    response = post(client, session)
    assert response.status_code == 502
    assert 'private' not in response.text
    assert sessions['review-test'][1] is session
    assert session.fields[0].user_response is None


@pytest.mark.parametrize('kind', ['docx', 'image'])
def test_non_pdf_exports_labeled_pdf_answer_sheet(review_session, kind):
    client, session = review_session
    session.document_type = kind
    session.filename = 'sample.docx' if kind == 'docx' else 'sample.png'
    response = post(client, session, value='Synthetic answer & <safe text>')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    with pymupdf.open(stream=response.content, filetype='pdf') as pdf:
        text = unicodedata.normalize('NFKC', ''.join(page.get_text() for page in pdf))
        assert 'answer sheet' in text
        assert 'original document has not been filled' in text
        assert 'Synthetic answer & <safe text>' in text


def test_invalid_choice_rejects_entire_snapshot(review_session):
    client, session = review_session
    session.fields[0].answer_type = 'choice'
    session.fields[0].options = ['Yes', 'No']
    assert post(client, session, value='Maybe').status_code == 422
    assert session.fields[0].user_response is None


def test_blank_answer_is_explicitly_skipped(review_session):
    client, session = review_session
    assert post(client, session, value='').status_code == 200
    field = sessions['review-test'][1].fields[0]
    assert field.status == 'skipped'
    assert not field.confirmed
