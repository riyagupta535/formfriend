import json
import pymupdf
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.parser import extract_pdf


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('STEP_API_KEY', raising=False)
    with TestClient(app) as client:
        yield client


def control_pdf():
    with pymupdf.open() as document:
        page = document.new_page()
        kinds = [('Full name', pymupdf.PDF_WIDGET_TYPE_TEXT),
                 ('Agree to contact', pymupdf.PDF_WIDGET_TYPE_CHECKBOX),
                 ('Contact method', pymupdf.PDF_WIDGET_TYPE_COMBOBOX),
                 ('Interests', pymupdf.PDF_WIDGET_TYPE_LISTBOX)]
        for i, (name, kind) in enumerate(kinds):
            w = pymupdf.Widget()
            w.field_name, w.field_type = name, kind
            w.rect = pymupdf.Rect(40, 40 + i * 80, 300, 90 + i * 80)
            if kind in (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX):
                w.choice_values = ['Email', 'Phone']
            if kind == pymupdf.PDF_WIDGET_TYPE_LISTBOX:
                w.field_flags = pymupdf.PDF_CH_FIELD_IS_MULTI_SELECT
            page.add_widget(w)
        return document.tobytes()


def test_controls_round_trip(client):
    uploaded = client.post('/sessions', files={'file': ('controls.pdf', control_pdf())})
    assert uploaded.status_code == 200
    session = uploaded.json()
    assert [f['answer_type'] for f in session['fields']] == ['text', 'checkbox', 'choice', 'multichoice']
    key = session['session_id']
    for field, value in zip(session['fields'], ['Alex', 'Yes', 'Phone', json.dumps(['Email', 'Phone'])]):
        response = client.post(f'/sessions/{key}/fields/{field["field_id"]}', json={'value': value})
        assert response.status_code == 200, response.text
    exported = client.get(f'/sessions/{key}/export')
    assert exported.status_code == 200
    with pymupdf.open(stream=exported.content, filetype='pdf') as doc:
        page = doc[0]
        widgets = list(page.widgets())
        assert widgets[0].field_value == 'Alex'
        assert widgets[1].field_value == widgets[1].on_state()
        assert widgets[2].field_value == 'Phone'
        assert doc.xref_get_key(widgets[3].xref, 'V')[1] == '[(Email)(Phone)]'
        assert doc.xref_get_key(widgets[3].xref, 'I')[1] == '[0 1]'
    field_id = session['fields'][1]['field_id']
    assert client.post(f'/sessions/{key}/fields/{field_id}', json={'value': 'maybe'}).status_code == 422
    client.post(f'/sessions/{key}/fields/{field_id}', json={'value': 'No'})
    with pymupdf.open(stream=client.get(f'/sessions/{key}/export').content, filetype='pdf') as doc:
        assert list(doc[0].widgets())[1].field_value == 'Off'
    client.delete(f'/sessions/{key}')


def test_printed_pdf_keeps_original_and_adds_answers(client):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 80), 'Full name:')
        page.insert_text((40, 140), 'What is your address?')
        data = doc.tobytes()
    uploaded = client.post('/sessions', files={'file': ('printed.pdf', data)})
    assert uploaded.status_code == 200
    session = uploaded.json()
    assert session['pdf_has_answer_sheet']
    assert len(session['fields']) == 2
    key = session['session_id']
    field = session['fields'][0]
    assert field['source_rect'] and field['extraction'] == 'printed'
    client.post(f'/sessions/{key}/fields/{field["field_id"]}', json={'value': 'Alex Example'})
    preview = client.get(f'/sessions/{key}/fields/{field["field_id"]}/source')
    assert preview.status_code == 200
    exported = client.get(f'/sessions/{key}/export')
    with pymupdf.open(stream=exported.content, filetype='pdf') as doc:
        assert doc[0].get_text().startswith('Full name:')
        assert 'Alex Example' in ''.join(page.get_text() for page in doc)
        assert len(doc) > 1
    client.delete(f'/sessions/{key}')


def scanned_pdf():
    with pymupdf.open() as scan:
        p = scan.new_page(width=600, height=400)
        p.insert_text((40, 100), 'Full name:', fontsize=28)
        pixels = p.get_pixmap().tobytes('png')
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=400)
        page.insert_image(page.rect, stream=pixels)
        return doc.tobytes()


def test_scanned_pdf_ocr(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('app.parser.shutil.which', lambda _: '/bin/tesseract')
    tsv = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    tsv += '5\t1\t1\t1\t1\t1\t100\t200\t120\t50\t95\tFull\n'
    tsv += '5\t1\t1\t1\t1\t2\t230\t200\t120\t50\t95\tname:\n'
    monkeypatch.setattr('app.parser.subprocess.run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=tsv))
    result = extract_pdf(scanned_pdf())
    assert result.fields[0].original_question == 'Full name:'
    assert result.fields[0].source_rect == [40, 80, 140, 100]
    assert any('OCR' in warning for warning in result.warnings)


def test_missing_ocr(monkeypatch):
    monkeypatch.setattr('app.parser.shutil.which', lambda _: None)
    with pytest.raises(ValueError, match='Install Tesseract'):
        extract_pdf(scanned_pdf())


def radio_pdf():
    # Build a standard /Btn parent with two child widget appearances.
    with pymupdf.open() as doc:
        refs = []
        for i in range(2):
            page = doc.new_page()
            w = pymupdf.Widget()
            w.field_name = f'choice{i}'
            w.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
            w.rect = pymupdf.Rect(40, 60, 60, 80)
            page.add_widget(w)
            refs.append(next(page.widgets()).xref)
        parent = doc.get_new_xref()
        doc.update_object(parent, f'<< /FT /Btn /Ff 32768 /T (Contact method) /Kids [{refs[0]} 0 R {refs[1]} 0 R] >>')
        for ref, state in zip(refs, ['Email', 'Phone']):
            _, normal = doc.xref_get_key(ref, 'AP/N')
            normal = normal.replace('/Yes', '/' + state)
            doc.xref_set_key(ref, 'AP/N', normal)
            doc.xref_set_key(ref, 'T', 'null')
            doc.xref_set_key(ref, 'Ff', '32768')
            doc.xref_set_key(ref, 'Parent', f'{parent} 0 R')
        doc.xref_set_key(doc.pdf_catalog(), 'AcroForm/Fields', f'[{parent} 0 R]')
        return doc.tobytes()


def test_radio_group_across_pages(client):
    uploaded = client.post('/sessions', files={'file': ('radio.pdf', radio_pdf())})
    assert uploaded.status_code == 200, uploaded.text
    session = uploaded.json()
    assert len(session['fields']) == 1
    field = session['fields'][0]
    assert field['options'] == ['Email', 'Phone']
    key = session['session_id']
    for selected in ['Email', 'Phone', '']:
        assert client.post(f'/sessions/{key}/fields/{field["field_id"]}', json={'value': selected}).status_code == 200
        exported = client.get(f'/sessions/{key}/export')
        assert exported.status_code == 200, exported.text
        with pymupdf.open(stream=exported.content, filetype='pdf') as doc:
            states = []
            for page in doc:
                w = next(page.widgets())
                states.append((w.field_value, w.on_state()))
            # Every child carries its parent's value; exactly the matching appearance is active.
            active = [state for value, state in states if value == state]
            assert active == ([selected] if selected else [])
    client.delete(f'/sessions/{key}')


def test_other_controls_do_not_reject_form(client):
    with pymupdf.open(stream=control_pdf(), filetype='pdf') as doc:
        page = doc[0]
        for i, kind in enumerate([pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.PDF_WIDGET_TYPE_BUTTON]):
            w = pymupdf.Widget()
            w.field_name = ['Office use only', 'Submit'][i]
            w.field_type = kind
            w.rect = pymupdf.Rect(40, 400 + i * 60, 250, 440 + i * 60)
            if i == 0:
                w.field_flags = pymupdf.PDF_FIELD_IS_READ_ONLY
                w.field_value = 'Keep this value'
            page.add_widget(w)
        data = doc.tobytes()
    uploaded = client.post('/sessions', files={'file': ('mixed.pdf', data)})
    assert uploaded.status_code == 200
    session = uploaded.json()
    assert len(session['fields']) == 4
    assert any('Read-only' in w for w in session['warnings'])
    exported = client.get(f'/sessions/{session["session_id"]}/export')
    with pymupdf.open(stream=exported.content, filetype='pdf') as doc:
        page = doc[0]
        widgets = {w.field_name: w for w in page.widgets()}
        assert widgets['Office use only'].field_value == 'Keep this value'
        assert 'Submit' in widgets
    client.delete(f'/sessions/{session["session_id"]}')


def test_locked_and_oversized_pdf_messages():
    with pymupdf.open() as doc:
        doc.new_page()
        locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw='secret')
    with pytest.raises(ValueError, match='unlocked PDF'):
        extract_pdf(locked)
    with pymupdf.open() as doc:
        for _ in range(31):
            doc.new_page()
        with pytest.raises(ValueError, match='30 pages'):
            extract_pdf(doc.tobytes())
