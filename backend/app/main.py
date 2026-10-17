import asyncio
import time
from uuid import uuid4
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from .models import Answer, Session
from .parser import extract_fields
from .conversation import mode, simplify

app = FastAPI(title="FormFriend")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])
# Memory-only sessions; expire after one hour, capped for this local prototype.
sessions: dict[str, tuple[float, Session]] = {}

def prune():
    for key, (created, _) in list(sessions.items()):
        if time.monotonic() - created > 3600:
            del sessions[key]

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
        raise HTTPException(413, "Please upload a PDF smaller than 10 MB.")
    if not (file.filename or "").lower().endswith(".pdf") or not data.startswith(b"%PDF-"):
        raise HTTPException(415, "Phase 1 accepts fillable PDF files only.")
    try:
        fields = await asyncio.to_thread(extract_fields, data)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except Exception:
        raise HTTPException(422, "This PDF could not be read. Please try another PDF.") from None
    try:
        for field in fields:
            field.simplified_question = await simplify(field.original_question)
    except Exception:
        raise HTTPException(502, "The question service could not respond. Please try again.") from None
    session = Session(session_id=uuid4().hex, filename=Path(file.filename).name,
                      mode=mode(), fields=fields,
                      warnings=[
                          "Check inferred field labels against the original form before answering.",
                          "Scanned PDFs still require the planned OCR pipeline.",
                      ])
    sessions[session.session_id] = (time.monotonic(), session)
    return session

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
    return {"cleared": True}
