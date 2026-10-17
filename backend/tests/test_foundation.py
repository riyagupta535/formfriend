import asyncio
import pymupdf
import pytest
from app.parser import extract_fields
from app.conversation import simplify
from app.main import answer, sessions
from app.models import Answer, Session
import time

def sample():
    document = pymupdf.open()
    page = document.new_page()
    widget = pymupdf.Widget()
    widget.field_name = "Full name"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(40, 70, 300, 100)
    page.add_widget(widget)
    data = document.tobytes()
    document.close()
    return data

def test_pdf_field_locations():
    fields = extract_fields(sample())
    assert len(fields) == 1
    assert fields[0].original_question == "Full name"
    assert fields[0].source_page == 1
    assert len(fields[0].source_rect) == 4

def test_nonfillable_rejected():
    with pymupdf.open() as doc:
        doc.new_page()
        with pytest.raises(ValueError, match="No fillable"):
            extract_fields(doc.tobytes())

def test_mock_is_explicit(monkeypatch):
    monkeypatch.delenv("STEP_API_KEY", raising=False)
    assert asyncio.run(simplify("Full name")) == "Please tell me: Full name"

def test_answer_mapping():
    fields = extract_fields(sample())
    sessions["test"] = (time.monotonic(), Session(session_id="test", filename="demo.pdf", mode="mock", fields=fields))
    result = answer("test", fields[0].field_id, Answer(value="Alex Example", confirmed=True))
    assert result.fields[0].interpreted_value == "Alex Example"
    assert result.fields[0].confirmed
    sessions.pop("test")

def test_upload_answer_clear(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv("STEP_API_KEY", raising=False)
    with TestClient(app) as client:
        uploaded = client.post('/sessions', files={'file': ('demo.pdf', sample(), 'application/pdf')})
        assert uploaded.status_code == 200
        session = uploaded.json()
        assert session['mode'] == 'mock'
        key = session['session_id']
        field_id = session['fields'][0]['field_id']
        saved = client.post(f'/sessions/{key}/fields/{field_id}', json={'value': 'Alex Example', 'confirmed': True})
        assert saved.json()['fields'][0]['confirmed']
        assert client.delete(f'/sessions/{key}').status_code == 200
        assert client.post(f'/sessions/{key}/fields/{field_id}', json={'value': 'x'}).status_code == 404
        assert client.post('/sessions', files={'file': ('bad.pdf', b'not a pdf')}).status_code == 415
