import pytest
import httpx
from fastapi.testclient import TestClient
from app.main import app

def test_missing_credentials(monkeypatch):
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    monkeypatch.delenv('ELEVENLABS_VOICE_ID', raising=False)
    with TestClient(app) as client:
        assert client.get('/voice/status').json() == {'available': False}
        assert client.post('/voice/speech', json={'text':'Your name?'}).status_code == 503
        assert client.post('/voice/speech', json={'text':''}).status_code == 422
        assert client.post('/voice/speech', json={'text':'a'*1501}).status_code == 422

def test_elevenlabs_request_and_audio(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-only-key')
    monkeypatch.setenv('ELEVENLABS_VOICE_ID', 'demo-voice')
    async def post(self, url, **kwargs):
        assert url.endswith('/text-to-speech/demo-voice')
        assert kwargs['headers']['xi-api-key'] == 'test-only-key'
        assert kwargs['json']['text'] == 'Your name?'
        return httpx.Response(200, content=b'demo-audio', request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    with TestClient(app) as client:
        response=client.post('/voice/speech',json={'text':'Your name?'})
        assert response.status_code == 200
        assert response.content == b'demo-audio'
        assert response.headers['content-type'] == 'audio/mpeg'
        assert response.headers['cache-control'] == 'no-store'

def test_provider_error_is_sanitized(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-only-key')
    monkeypatch.setenv('ELEVENLABS_VOICE_ID', 'demo-voice')
    async def post(self, url, **kwargs):
        return httpx.Response(401, text='provider secret detail',request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    with TestClient(app) as client:
        response=client.post('/voice/speech',json={'text':'Your name?'})
        assert response.status_code == 502
        assert 'secret' not in response.text


@pytest.mark.parametrize('language', ['en', 'es', 'zh', 'fil', 'vi', 'ar', 'fr', 'ko', 'pt', 'hi'])
def test_speech_selects_requested_language(monkeypatch, language):
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-only-key')
    monkeypatch.setenv('ELEVENLABS_VOICE_ID', 'demo-voice')
    async def post(self, url, **kwargs):
        assert kwargs['json']['language_code'] == language
        assert kwargs['json']['text'] == '¿Cómo te llamas?'
        return httpx.Response(200, content=b'audio', request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    with TestClient(app) as client:
        assert client.post('/voice/speech', json={'text': '¿Cómo te llamas?', 'language': language}).status_code == 200
