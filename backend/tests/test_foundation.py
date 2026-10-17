import asyncio
import pymupdf
import pytest
from app.parser import extract_fields
from app.conversation import simplify
from app.main import answer, sessions
from app.models import Answer, Session
from app.ocr import OCRLine, _cutoff, _label_fields, _numbered_fields
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

def test_nonfillable_rejected():
    with pymupdf.open() as doc:
        doc.new_page()
        with pytest.raises(ValueError, match="No fillable"):
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
