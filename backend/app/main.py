import asyncio
import os
import httpx
import pymupdf
import time
from uuid import uuid4
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from urllib.parse import quote
from .documents import extract_docx, extract_image, export_document
from .models import Answer, Session
from .parser import extract_fields
from .conversation import mode, simplify

app = FastAPI(title="FormFriend")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://localhost:3001"],
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])
# Memory-only sessions; expire after one hour, capped for this local prototype.
sessions: dict[str, tuple[float, Session]] = {}
documents: dict[str, bytes] = {}

def prune():
    for key, (created, _) in list(sessions.items()):
        if time.monotonic() - created > 3600:
            del sessions[key]
            documents.pop(key, None)

def get_session(key: str):
    prune()
    if key not in sessions:
        raise HTTPException(404, "Session expired or not found. Please upload again.")
    return sessions[key][1]

@app.get("/health")
def health():
    return {"status": "ok", "mode": mode()}

@app.post("/sessions", response_model=Session)
async def upload(file: UploadFile = File(...)):
    prune()
    if len(sessions) >= 50:
        raise HTTPException(503, "Demo is busy. Please try again shortly.")
    try:
        data = await file.read(10 * 1024 * 1024 + 1)
    finally:
        await file.close()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Please upload a file smaller than 10 MB.")
    suffix = Path(file.filename or '').suffix.lower()
    document_type = 'pdf' if suffix == '.pdf' else 'docx' if suffix == '.docx' else 'image'
    if suffix not in {'.pdf', '.docx', '.png', '.jpg', '.jpeg'}:
        raise HTTPException(415, 'Please upload a PDF, DOCX, PNG, or JPG file.')
    if suffix == '.pdf' and not data.startswith(b'%PDF-'):
        raise HTTPException(415, 'This file is not a valid PDF.')
    try:
        parser = extract_fields if document_type == 'pdf' else extract_docx if document_type == 'docx' else extract_image
        fields = await asyncio.to_thread(parser, data)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except Exception:
        raise HTTPException(422, "This document could not be read. Please try another file.") from None
    try:
        for field in fields:
            field.simplified_question = await simplify(field.original_question)
    except Exception:
        raise HTTPException(502, "The question service could not respond. Please try again.") from None
    warnings = ["Check extracted labels and answers before using your document."]
    if document_type == "pdf" and any(
        field.source_kind in {"text-layer", "ocr"} for field in fields
    ):
        warnings.append(
            "This PDF is not fillable. FormFriend can collect answers, but export must use an answer sheet."
        )
    if document_type == "pdf" and any(field.source_kind == "ocr" for field in fields):
        warnings.append(
            "These questions came from OCR. Check every question against the scanned page because OCR can make mistakes."
        )
    if document_type == "image":
        warnings.append(
            "OCR can miss or misread questions. Upload a fillable version to complete the original document."
        )
    elif document_type == "docx":
        warnings.append(
            "Word questions are identified by paragraph punctuation. Page references are approximate; answers are appended to matching paragraphs."
        )
    session = Session(session_id=uuid4().hex, filename=Path(file.filename).name, document_type=document_type,
                      mode=mode(), fields=fields, warnings=warnings)
    sessions[session.session_id] = (time.monotonic(), session)
    documents[session.session_id] = data
    return session

@app.get("/sessions/{key}", response_model=Session)
def retrieve(key: str):
    return get_session(key)

@app.get("/sessions/{key}/export")
async def export(key: str):
    session = get_session(key)
    data, content_type = await asyncio.to_thread(export_document, session, documents[key])
    filename = 'formfriend-answers.txt' if content_type.startswith('text/plain') else 'formfriend-' + session.filename
    return Response(data, media_type=content_type, headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)})

@app.get("/sessions/{key}/fields/{field_id}/source")
async def source(key: str, field_id: str):
    session = get_session(key)
    field = next((f for f in session.fields if f.field_id == field_id), None)
    if field is None or session.document_type != 'pdf':
        raise HTTPException(404, 'Source preview is available for PDF fields only.')
    def render():
        with pymupdf.open(stream=documents[key], filetype='pdf') as document:
            page = document[field.source_page - 1]
            page.draw_rect(pymupdf.Rect(field.source_rect), color=(0.1, 0.6, 0.5), width=2)
            return page.get_pixmap(matrix=pymupdf.Matrix(1, 1)).tobytes('png')
    return Response(await asyncio.to_thread(render), media_type='image/png')

@app.get("/sessions/{key}/fields/{field_id}/speech")
async def speech(key: str, field_id: str):
    session = get_session(key)
    field = next((f for f in session.fields if f.field_id == field_id), None)
    if field is None:
        raise HTTPException(404, 'Field not found.')
    api_key, voice = os.getenv('ELEVENLABS_API_KEY'), os.getenv('ELEVENLABS_VOICE_ID')
    if not api_key or not voice:
        raise HTTPException(503, 'ElevenLabs is not configured. Use browser speech instead.')
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post('https://api.elevenlabs.io/v1/text-to-speech/' + quote(voice, safe=''),
                headers={'xi-api-key': api_key},
                json={'text': field.simplified_question, 'model_id': 'eleven_multilingual_v2'})
            response.raise_for_status()
            return Response(response.content, media_type='audio/mpeg')
    except httpx.HTTPError:
        raise HTTPException(502, 'Voice service unavailable. Use browser speech instead.') from None

@app.post("/sessions/{key}/fields/{field_id}", response_model=Session)
def answer(key: str, field_id: str, answer: Answer):
    session = get_session(key)
    field = next((f for f in session.fields if f.field_id == field_id), None)
    if field is None:
        raise HTTPException(404, "Field not found.")
    field.user_response = answer.value
    field.interpreted_value = answer.value
    field.confirmed = answer.confirmed
    field.status = "answered" if answer.value.strip() else "skipped"
    return session

@app.delete("/sessions/{key}")
def clear(key: str):
    sessions.pop(key, None)
    documents.pop(key, None)
    return {"cleared": True}

from .voice import router as voice_router
app.include_router(voice_router)
