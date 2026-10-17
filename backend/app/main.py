import asyncio
import json
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
from .documents import extract_docx, extract_image, extract_images, export_document
from .models import Answer, Session
from .parser import extract_pdf
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
async def upload(file: UploadFile | None = File(default=None),
                 files: list[UploadFile] | None = File(default=None)):
    prune()
    if len(sessions) >= 50:
        raise HTTPException(503, "Demo is busy. Please try again shortly.")
    uploads = ([file] if file else []) + (files or [])
    if not uploads:
        raise HTTPException(400, "Choose a file to upload.")
    if len(uploads) > 10:
        raise HTTPException(413, "Upload no more than 10 screenshots for one form.")
    payloads = []
    for upload_file in uploads:
        try:
            payload = await upload_file.read(10 * 1024 * 1024 + 1)
        finally:
            await upload_file.close()
        if len(payload) > 10 * 1024 * 1024:
            raise HTTPException(413, "Each uploaded file must be smaller than 10 MB.")
        payloads.append(payload)
    if sum(len(payload) for payload in payloads) > 30 * 1024 * 1024:
        raise HTTPException(413, "The combined screenshot upload must be smaller than 30 MB.")

    suffixes = [Path(upload_file.filename or '').suffix.lower() for upload_file in uploads]
    if len(uploads) > 1 and any(suffix not in {'.png', '.jpg', '.jpeg'} for suffix in suffixes):
        raise HTTPException(415, "Multiple uploads must all be PNG or JPG screenshots.")
    suffix = suffixes[0]
    document_type = 'pdf' if suffix == '.pdf' else 'docx' if suffix == '.docx' else 'image'
    if any(item not in {'.pdf', '.docx', '.png', '.jpg', '.jpeg'} for item in suffixes):
        raise HTTPException(415, 'Please upload a PDF, DOCX, PNG, or JPG file.')
    if suffix == '.pdf' and not payloads[0].startswith(b'%PDF-'):
        raise HTTPException(415, 'This file is not a valid PDF.')
    duplicate_count = 0
    try:
        pdf_warnings = []
        if len(payloads) > 1:
            fields, duplicate_count = await asyncio.to_thread(extract_images, payloads)
        elif document_type == 'pdf':
            extracted = await asyncio.to_thread(extract_pdf, payloads[0])
            fields, pdf_warnings = extracted.fields, extracted.warnings
        else:
            parser = extract_docx if document_type == 'docx' else extract_image
            fields = await asyncio.to_thread(parser, payloads[0])
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except Exception:
        raise HTTPException(422, "This document could not be read. Please try another file.") from None
    # Opening a form must not wait for an unbounded series of provider calls.
    # Preserve original wording whenever simplification is slow or unavailable.
    warnings = ["Check extracted labels and answers before using your document."]
    semaphore = asyncio.Semaphore(3)
    simplified_ids = set()
    for field in fields:
        field.simplified_question = field.original_question
    async def simplify_field(field):
        async with semaphore:
            try:
                question = await simplify(field.original_question)
            except Exception:
                return
            field.simplified_question = question
            simplified_ids.add(field.field_id)
    try:
        await asyncio.wait_for(asyncio.gather(*(simplify_field(field) for field in fields)), timeout=20)
    except TimeoutError:
        pass
    remaining = len(fields) - len(simplified_ids)
    if remaining:
        warnings.append(
            f"{remaining} question(s) use the original form wording because simplification was slow or unavailable. "
            "You can still answer and review your form."
        )
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
        if len(payloads) > 1:
            warnings.append(
                f"Combined {len(payloads)} screenshots and removed {duplicate_count} overlapping question"
                f"{'s' if duplicate_count != 1 else ''}."
            )
    elif document_type == "docx":
        warnings.append(
            "Word questions are identified by paragraph punctuation. Page references are approximate; answers are appended to matching paragraphs."
        )
    filename = Path(uploads[0].filename or "upload").name
    if len(uploads) > 1:
        filename = f"{filename} + {len(uploads) - 1} screenshot{'s' if len(uploads) > 2 else ''}"
    session = Session(session_id=uuid4().hex, filename=filename, document_type=document_type,
                      mode=mode(), fields=fields,
                      pdf_has_answer_sheet=any(f.extraction == "printed" for f in fields),
                      warnings=warnings + pdf_warnings)
    sessions[session.session_id] = (time.monotonic(), session)
    documents[session.session_id] = payloads[0]
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
    # Retain the session endpoint for compatibility; both UIs share the branch's provider logic.
    from .voice import SpeechRequest, speech as create_speech
    return await create_speech(SpeechRequest(text=field.simplified_question))

@app.post("/sessions/{key}/fields/{field_id}", response_model=Session)
def answer(key: str, field_id: str, answer: Answer):
    session = get_session(key)
    field = next((f for f in session.fields if f.field_id == field_id), None)
    if field is None:
        raise HTTPException(404, "Field not found.")
    if answer.value.strip():
        if field.answer_type in ('checkbox', 'choice') and answer.value not in field.options:
            raise HTTPException(422, 'Please choose one of the available options.')
        if field.answer_type == 'multichoice':
            try:
                selected = json.loads(answer.value)
            except (ValueError, TypeError):
                raise HTTPException(422, 'Please choose from the available options.') from None
            if not isinstance(selected, list) or any(not isinstance(v, str) or v not in field.options for v in selected):
                raise HTTPException(422, 'Please choose from the available options.')
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

from .review import router as review_router
app.include_router(review_router)
