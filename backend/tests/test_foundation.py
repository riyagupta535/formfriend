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

def test_empty_pdf_rejected():
    with pymupdf.open() as doc:
        doc.new_page()
        with pytest.raises(ValueError, match="No questions"):
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

def test_pdf_export(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv('STEP_API_KEY', raising=False)
    with TestClient(app) as client:
        session = client.post('/sessions', files={'file': ('form.pdf', sample())}).json()
        key = session['session_id']
        field_id = session['fields'][0]['field_id']
        client.post(f'/sessions/{key}/fields/{field_id}', json={'value': 'Sam Sample', 'confirmed': True})
        exported = client.get(f'/sessions/{key}/export')
        assert exported.status_code == 200
        with pymupdf.open(stream=exported.content, filetype='pdf') as document:
            assert next(document[0].widgets()).field_value == 'Sam Sample'
        assert client.get(f'/sessions/{key}').json()['filename'] == 'form.pdf'
        client.delete(f'/sessions/{key}')
        assert client.get(f'/sessions/{key}/export').status_code == 404


def test_docx_export(monkeypatch):
    from io import BytesIO
    import zipfile
    from fastapi.testclient import TestClient
    from app.main import app
    from app.documents import paragraphs, W
    monkeypatch.delenv('STEP_API_KEY', raising=False)
    data = BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Full name:</w:t></w:r></w:p></w:body></w:document>')
        archive.writestr('unchanged.txt', 'preserved')
    with TestClient(app) as client:
        uploaded = client.post('/sessions', files={'file': ('form.docx', data.getvalue())})
        assert uploaded.status_code == 200
        session = uploaded.json()
        key = session['session_id']
        assert session['document_type'] == 'docx'
        field_id = session['fields'][0]['field_id']
        client.post(f'/sessions/{key}/fields/{field_id}', json={'value': 'Alex & Sam'})
        exported = client.get(f'/sessions/{key}/export')
        _, items = paragraphs(exported.content)
        assert ''.join(t.text or '' for t in items[0].iter(W + 't')) == 'Full name: Alex & Sam'
        with zipfile.ZipFile(BytesIO(exported.content)) as archive:
            assert archive.read('unchanged.txt') == b'preserved'
        client.delete(f'/sessions/{key}')


def test_ocr_unavailable(monkeypatch):
    from app.documents import extract_image
    monkeypatch.setattr('app.documents.shutil.which', lambda _: None)
    with pytest.raises(ValueError, match='Tesseract'):
        extract_image(b'image')


def test_screenshot_export(monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv('STEP_API_KEY', raising=False)
    monkeypatch.setattr('app.documents.shutil.which', lambda _: '/bin/tesseract')
    monkeypatch.setattr('app.documents.subprocess.run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='Application\nFull name:\nWhat is your address?'))
    with pymupdf.open() as document:
        image = document.new_page(width=300, height=300).get_pixmap().tobytes('png')
    with TestClient(app) as client:
        uploaded = client.post('/sessions', files={'file': ('screenshot.png', image)})
        assert uploaded.status_code == 200
        session = uploaded.json()
        assert session['document_type'] == 'image'
        assert len(session['fields']) == 2
        key = session['session_id']
        client.post(f'/sessions/{key}/fields/image:0', json={'value': 'Sam'})
        exported = client.get(f'/sessions/{key}/export')
        assert 'Full name:\nSam' in exported.text
        assert '[No answer provided]' in exported.text
        client.delete(f'/sessions/{key}')


def test_pdf_source_preview_and_unconfigured_speech(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv('STEP_API_KEY', raising=False)
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    with TestClient(app) as client:
        session = client.post('/sessions', files={'file': ('form.pdf', sample())}).json()
        key, field_id = session['session_id'], session['fields'][0]['field_id']
        preview = client.get(f'/sessions/{key}/fields/{field_id}/source')
        assert preview.status_code == 200
        assert preview.content.startswith(b'\x89PNG')
        assert client.get(f'/sessions/{key}/fields/{field_id}/speech').status_code == 503
        assert client.get(f'/sessions/{key}/fields/missing/source').status_code == 404
        client.delete(f'/sessions/{key}')


def test_elevenlabs_request(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv('STEP_API_KEY', raising=False)
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-key')
    monkeypatch.setenv('ELEVENLABS_VOICE_ID', 'test-voice')
    async def fake_post(self, url, **kwargs):
        assert url.endswith('/text-to-speech/test-voice')
        assert kwargs['headers']['xi-api-key'] == 'test-key'
        assert kwargs['json']['text'] == 'Please tell me: Full name'
        return httpx.Response(200, content=b'mock-audio', request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.AsyncClient, 'post', fake_post)
    with TestClient(app) as client:
        session = client.post('/sessions', files={'file': ('form.pdf', sample())}).json()
        key, field_id = session['session_id'], session['fields'][0]['field_id']
        response = client.get(f'/sessions/{key}/fields/{field_id}/speech')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'audio/mpeg'
        assert response.content == b'mock-audio'
        client.delete(f'/sessions/{key}')
