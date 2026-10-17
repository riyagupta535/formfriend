import asyncio
import pymupdf
import pytest
from app.parser import extract_fields
from app.conversation import simplify
from app.main import answer, sessions
from app.models import Answer, FormField, Session
from app.ocr import (
    OCRLine, _cutoff, _label_fields, _numbered_fields,
    deduplicate_image_fields, extract_image_fields,
)
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

def sample_with_unlabeled_controls():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 60), "Applicant legal name")
    text = pymupdf.Widget()
    text.field_name = "f1_01[0]"
    text.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    text.rect = pymupdf.Rect(40, 70, 300, 100)
    page.add_widget(text)
    for index, option in enumerate(("Single", "Married filing jointly")):
        y = 125 + index * 24
        checkbox = pymupdf.Widget()
        checkbox.field_name = f"filing_status[{index}]"
        checkbox.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
        checkbox.rect = pymupdf.Rect(40, y, 52, y + 12)
        page.add_widget(checkbox)
        page.insert_text((60, y + 10), option)
    data = document.tobytes()
    document.close()
    return data

def sample_nonfillable_form():
    document = pymupdf.open()
    page = document.new_page()
    prompts = (
        (50, "1 Full legal name"),
        (120, "2 Mailing address"),
        (190, "3 Phone number"),
    )
    for y, prompt in prompts:
        page.insert_text((40, y), prompt)
        page.draw_line((40, y + 30), (350, y + 30))
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

def test_unlabeled_text_uses_nearby_page_text():
    fields = extract_fields(sample_with_unlabeled_controls())
    assert fields[0].original_question == "Applicant legal name"
    assert fields[0].source_context == "Applicant legal name"
    assert fields[0].pdf_field_names == ["f1_01[0]"]

def test_related_checkboxes_are_grouped_as_one_choice():
    fields = extract_fields(sample_with_unlabeled_controls())
    choice = fields[1]
    assert choice.answer_type == "choice"
    assert choice.options == ["Single", "Married filing jointly"]
    assert len(choice.pdf_field_names) == 2

def test_nonfillable_text_form_extracts_numbered_prompts():
    fields = extract_fields(sample_nonfillable_form())
    assert [field.original_question for field in fields] == [
        "1 Full legal name", "2 Mailing address", "3 Phone number"
    ]
    assert all(field.source_kind == "text-layer" for field in fields)
    assert all(field.pdf_field_names == [] for field in fields)
    assert [field.question_number for field in fields] == ["1", "2", "3"]
    assert all(field.section_title is None for field in fields)

def test_ocr_lines_keep_question_identity_and_confidence():
    lines = [
        OCRLine("1Name of applicant", pymupdf.Rect(40, 50, 220, 65), .98),
        OCRLine("2", pymupdf.Rect(40, 100, 48, 115), .96),
        OCRLine("Mailing address", pymupdf.Rect(60, 100, 220, 115), .97),
        OCRLine("3bEligibility confirmation", pymupdf.Rect(40, 150, 250, 165), .91),
        OCRLine("Certification", pymupdf.Rect(40, 210, 150, 225), .99),
        OCRLine("1.Not a form question", pymupdf.Rect(40, 240, 250, 255), .99),
    ]
    cutoff = _cutoff(lines, 792)
    fields = _numbered_fields(lines, 1, 612, cutoff)
    assert [field.question_number for field in fields] == ["1", "2", "3b"]
    assert fields[0].original_question == "1 Name of applicant"
    assert fields[1].original_question == "2 Mailing address"
    assert all(field.source_kind == "ocr" for field in fields)
    assert all(field.ocr_confidence is not None for field in fields)

def test_ocr_recognizes_common_unnumbered_w9_labels():
    line = OCRLine("Socialsecuritynumber", pymupdf.Rect(400, 300, 520, 315), .99)
    fields = _label_fields([line], 1, 792, [])
    assert fields[0].original_question == "Social security number"
    assert fields[0].source_context == "Socialsecuritynumber"

def test_screenshot_ocr_extracts_labels_choices_and_numbered_lines(monkeypatch):
    lines = [
        OCRLine("Your first name and middle initial", pymupdf.Rect(40, 40, 250, 55), .98),
        OCRLine("Last name", pymupdf.Rect(300, 40, 380, 55), .97),
        OCRLine("Filing Status", pymupdf.Rect(40, 80, 140, 95), .99),
        OCRLine("Single", pymupdf.Rect(160, 80, 220, 95), .99),
        OCRLine("Head of household (HOH)", pymupdf.Rect(250, 80, 450, 95), .98),
        OCRLine("1a", pymupdf.Rect(40, 130, 65, 145), .99),
        OCRLine("Total wages", pymupdf.Rect(75, 130, 180, 145), .96),
    ]
    monkeypatch.setattr('app.ocr._ocr_image', lambda _: (lines, 600, 800))
    fields = extract_image_fields(b'ignored')
    assert next(field for field in fields if field.field_id == 'image:ocr:your-name').ocr_confidence == .98
    filing = next(field for field in fields if field.field_id == 'image:ocr:filing-status')
    assert filing.answer_type == 'choice'
    assert filing.options == ['Single', 'Head of household']
    income = next(field for field in fields if field.question_number == '1a')
    assert income.field_id == 'image:ocr:line-1a'
    assert income.original_question == '1a Total wages'

def test_overlapping_screenshot_questions_are_deduplicated():
    first = FormField(
        field_id='first', question_number='1a', original_question='1a Total wages from Forms W-2',
        source_page=1, source_rect=[10, 10, 200, 20], source_kind='ocr', ocr_confidence=.91,
    )
    clearer_overlap = FormField(
        field_id='second', question_number='1a', original_question='1a Totalwages from Forms W-2',
        source_page=1, source_rect=[10, 300, 200, 310], source_kind='ocr', ocr_confidence=.98,
    )
    different_line = FormField(
        field_id='third', question_number='1b', original_question='1b Total wages from Forms W-2',
        source_page=1, source_rect=[10, 330, 200, 340], source_kind='ocr', ocr_confidence=.99,
    )
    fields, removed = deduplicate_image_fields([[first], [clearer_overlap, different_line]])
    assert removed == 1
    assert len(fields) == 2
    assert fields[0].ocr_confidence == .98
    assert fields[0].source_page == 2
    assert fields[0].field_id == 'image:ocr:1a'
    assert fields[1].field_id == 'image:ocr:1b'

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


def test_nonfillable_pdf_exports_answer_sheet(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv('STEP_API_KEY', raising=False)
    with TestClient(app) as client:
        session = client.post(
            '/sessions', files={'file': ('regular.pdf', sample_nonfillable_form())}
        ).json()
        key = session['session_id']
        field_id = session['fields'][0]['field_id']
        client.post(
            f'/sessions/{key}/fields/{field_id}',
            json={'value': 'Alex Example', 'confirmed': True},
        )
        exported = client.get(f'/sessions/{key}/export')
        assert exported.status_code == 200
        assert exported.headers['content-type'].startswith('application/pdf')
        with pymupdf.open(stream=exported.content, filetype='pdf') as document:
            assert len(document) > 1
            assert 'Alex Example' in ''.join(page.get_text() for page in document)
        assert 'formfriend-regular.pdf' in exported.headers['content-disposition']


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


def test_invalid_screenshot_rejected():
    from app.documents import extract_image
    with pytest.raises(ValueError, match='could not be read'):
        extract_image(b'image')


def test_screenshot_export(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import FormField
    monkeypatch.delenv('STEP_API_KEY', raising=False)
    monkeypatch.setattr('app.documents.extract_image_fields', lambda _: [
        FormField(field_id='image:ocr:full-name', original_question='Full name',
                  source_page=1, source_rect=[10, 10, 100, 20], source_kind='ocr',
                  ocr_confidence=.98),
        FormField(field_id='image:ocr:address', original_question='What is your address?',
                  source_page=1, source_rect=[10, 30, 150, 40], source_kind='ocr',
                  ocr_confidence=.97),
    ])
    with pymupdf.open() as document:
        image = document.new_page(width=300, height=300).get_pixmap().tobytes('png')
    with TestClient(app) as client:
        uploaded = client.post('/sessions', files={'file': ('screenshot.png', image)})
        assert uploaded.status_code == 200
        session = uploaded.json()
        assert session['document_type'] == 'image'
        assert len(session['fields']) == 2
        key = session['session_id']
        client.post(f'/sessions/{key}/fields/image:ocr:full-name', json={'value': 'Sam'})
        exported = client.get(f'/sessions/{key}/export')
        assert 'Full name\nSam' in exported.text
        assert '[No answer provided]' in exported.text
        client.delete(f'/sessions/{key}')


def test_multiple_screenshot_upload(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import FormField
    monkeypatch.delenv('STEP_API_KEY', raising=False)
    fields = [FormField(
        field_id='image:ocr:name', original_question='Full name', source_page=1,
        source_rect=[10, 10, 100, 20], source_kind='ocr', ocr_confidence=.98,
    )]
    monkeypatch.setattr('app.main.extract_images', lambda _: (fields, 3))
    with TestClient(app) as client:
        uploaded = client.post('/sessions', files=[
            ('files', ('top.png', b'first', 'image/png')),
            ('files', ('bottom.png', b'second', 'image/png')),
        ])
        assert uploaded.status_code == 200
        session = uploaded.json()
        assert session['filename'] == 'top.png + 1 screenshot'
        assert len(session['fields']) == 1
        assert any('removed 3 overlapping questions' in warning for warning in session['warnings'])


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
