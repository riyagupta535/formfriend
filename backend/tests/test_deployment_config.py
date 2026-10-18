from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.config import cors_origins


def test_local_origins_are_the_default(monkeypatch):
    monkeypatch.delenv('CORS_ORIGINS', raising=False)
    assert cors_origins() == ['http://localhost:3000', 'http://localhost:3001']


def test_deployed_origin_is_allowed_but_unrelated_previews_are_not(monkeypatch):
    monkeypatch.setenv('CORS_ORIGINS', ' https://forma.vercel.app/, https://forma.vercel.app ')
    origins = cors_origins()
    assert origins == ['https://forma.vercel.app']
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['POST'], allow_headers=['Content-Type'])
    client = TestClient(app)
    headers = {'Origin': origins[0], 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'}
    allowed = client.options('/sessions', headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers['access-control-allow-origin'] == origins[0]
    headers['Origin'] = 'https://unrelated.vercel.app'
    rejected = client.options('/sessions', headers=headers)
    assert rejected.status_code == 400
    assert 'access-control-allow-origin' not in rejected.headers
