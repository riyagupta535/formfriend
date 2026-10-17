import asyncio
import pymupdf
from fastapi.testclient import TestClient
from app.main import app


def demo_pdf():
    with pymupdf.open() as doc:
        page = doc.new_page()
        for i in range(4):
            widget = pymupdf.Widget()
            widget.field_name = f'Sample field {i}'
            widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
            widget.rect = pymupdf.Rect(40, 50 + 50*i, 300, 80 + 50*i)
            page.add_widget(widget)
        return doc.tobytes()


def test_simplification_failure_keeps_original_questions(monkeypatch):
    async def fail(question):
        raise RuntimeError('provider private details')
    monkeypatch.setattr('app.main.simplify', fail)
    with TestClient(app) as client:
        result = client.post('/sessions', files={'file': ('demo.pdf', demo_pdf())})
        assert result.status_code == 200
        data = result.json()
        assert all(f['simplified_question'] == f['original_question'] for f in data['fields'])
        assert any('original form wording' in w for w in data['warnings'])
        assert 'private' not in result.text
        client.delete('/sessions/' + data['session_id'])


def test_simplification_is_bounded_and_preserves_mapping(monkeypatch):
    active = peak = 0
    async def simplify(question):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.01)
        active -= 1
        return 'Simple: ' + question
    monkeypatch.setattr('app.main.simplify', simplify)
    with TestClient(app) as client:
        result = client.post('/sessions', files={'file': ('demo.pdf', demo_pdf())})
        assert result.status_code == 200
        data = result.json()
        assert 1 < peak <= 3
        assert all(f['simplified_question'] == 'Simple: ' + f['original_question'] for f in data['fields'])
        client.delete('/sessions/' + data['session_id'])


def test_simplification_timeout_opens_form_and_cancels_pending_work(monkeypatch):
    cancelled = []
    async def slow(question):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(question)
    real_wait_for = asyncio.wait_for
    async def short_timeout(task, timeout):
        return await real_wait_for(task, timeout=.02)
    monkeypatch.setattr('app.main.simplify', slow)
    monkeypatch.setattr('app.main.asyncio.wait_for', short_timeout)
    with TestClient(app) as client:
        result = client.post('/sessions', files={'file': ('demo.pdf', demo_pdf())})
        assert result.status_code == 200
        assert cancelled
        assert all(f['simplified_question'] == f['original_question'] for f in result.json()['fields'])
        client.delete('/sessions/' + result.json()['session_id'])
