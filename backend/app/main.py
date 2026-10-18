import asyncio
import json
import logging
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
from .models import Answer, Session, TableLookupRequest, WorksheetAnswers, WorksheetResult
from .parser import extract_pdf
from .conversation import mode, simplify, simplify_fields
from .worksheets import calculate_worksheet
from .table_lookups import lookup_wage_table

app = FastAPI(title="FormFriend")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://localhost:3001"],
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])
# Memory-only sessions; expire after one hour, capped for this local prototype.
sessions: dict[str, tuple[float, Session]] = {}
documents: dict[str, bytes] = {}
simplification_tasks: dict[str, asyncio.Task] = {}
logger = logging.getLogger("formfriend.sessions")
_default_simplify = simplify


async def simplify_legacy_upload(fields):
    """Support the original bounded upload simplifier during the transition."""
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
        await asyncio.wait_for(
            asyncio.gather(*(simplify_field(field) for field in fields)),
            timeout=20,
        )
    except TimeoutError:
        pass
    return len(fields) - len(simplified_ids)

def prune():
    for key, (created, _) in list(sessions.items()):
        if time.monotonic() - created > 3600:
            del sessions[key]
            documents.pop(key, None)
            task = simplification_tasks.pop(key, None)
            if task:
                task.cancel()

def get_session(key: str):
    prune()
    if key not in sessions:
        raise HTTPException(404, "Session expired or not found. Please upload again.")
    return sessions[key][1]

async def complete_simplification(key: str):
    entry = sessions.get(key)
    if entry is None:
        return
    session = entry[1]
    session.simplification_status = "running"
    try:
        warnings = await simplify_fields(session.fields)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Unexpected Gemini background failure; session_id=%s", key)
        for field in session.fields:
            if field.simplification_status == "pending":
                field.simplification_status = "failed"
        warnings = [
            "Gemini could not simplify these questions."
        ]
    if key not in sessions:
        return
    session.warnings.extend(warning for warning in warnings if warning not in session.warnings)
    session.simplification_status = "partial" if warnings else "complete"

def start_simplification(key: str):
    task = asyncio.create_task(complete_simplification(key))
    simplification_tasks[key] = task
    def discard(completed: asyncio.Task):
        if simplification_tasks.get(key) is completed:
            simplification_tasks.pop(key, None)
    task.add_done_callback(discard)

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
    active_mode = mode()
    legacy_remaining = None
    if simplify is not _default_simplify:
        legacy_remaining = await simplify_legacy_upload(fields)
    elif active_mode == "mock":
        await simplify_fields(fields)
    else:
        for field in fields:
            workflow = field.worksheet or field.eligibility_workflow or field.table_lookup or field.pay_period_calculation
            sourced_calculation = bool(field.calculation and field.calculation.source_field_ids)
            field.simplified_question = (
                workflow.intro_question if workflow else field.simplified_question
                if sourced_calculation else field.original_question
            )
            field.helper_text = workflow.intro_helper_text if workflow else field.helper_text if sourced_calculation else None
            field.subquestions = []
            field.decision_tree = None
            field.simplification_status = "complete" if workflow or sourced_calculation else "pending"
            field.simplification_confidence = "high" if workflow or sourced_calculation else "low"
    warnings = ["Check extracted labels and answers before using your document."]
    if legacy_remaining:
        warnings.append(
            f"{legacy_remaining} question(s) use the original form wording because simplification was slow or unavailable. "
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
                      mode=active_mode,
                      simplification_status="complete" if active_mode == "mock" or legacy_remaining is not None else "pending",
                      fields=fields,
                      pdf_has_answer_sheet=any(f.extraction == "printed" for f in fields),
                      warnings=warnings + pdf_warnings)
    sessions[session.session_id] = (time.monotonic(), session)
    documents[session.session_id] = payloads[0]
    if active_mode != "mock" and legacy_remaining is None:
        start_simplification(session.session_id)
    return session

@app.get("/sessions/{key}", response_model=Session)
def retrieve(key: str):
    session = get_session(key)
    if session.agent_state:
        from .agent_tools import visible_fields
        return session.model_copy(update={"fields": visible_fields(session)})
    return session

@app.get("/sessions/{key}/export")
async def export(key: str):
    session = get_session(key)
    if session.agent_state:
        raise HTTPException(409, "Use the final review PDF export for this agent session.")
    data, content_type = await asyncio.to_thread(export_document, session, documents[key])
    filename = 'formfriend-answers.txt' if content_type.startswith('text/plain') else 'formfriend-' + session.filename
    return Response(data, media_type=content_type, headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)})

@app.get("/sessions/{key}/fields/{field_id}/source")
async def source(key: str, field_id: str):
    session = get_session(key)
    field = next((f for f in session.fields if f.field_id == field_id), None)
    if field is None or session.document_type != 'pdf' or len(field.source_rect) != 4 or field.source_page < 1:
        raise HTTPException(404, 'Source preview is available for PDF fields only.')
    def render():
        with pymupdf.open(stream=documents[key], filetype='pdf') as document:
            page = document[field.source_page - 1]
            page.draw_rect(pymupdf.Rect(field.source_rect), color=(0.1, 0.6, 0.5), width=2)
            return page.get_pixmap(matrix=pymupdf.Matrix(1, 1)).tobytes('png')
    return Response(await asyncio.to_thread(render), media_type='image/png')

@app.get("/sessions/{key}/fields/{field_id}/worksheet/source")
async def worksheet_source(key: str, field_id: str):
    session = get_session(key)
    field = next((item for item in session.fields if item.field_id == field_id), None)
    if field is None or field.worksheet is None or session.document_type != "pdf":
        raise HTTPException(404, "Worksheet source is available for supported PDF worksheets only.")
    def render():
        with pymupdf.open(stream=documents[key], filetype="pdf") as document:
            page = document[field.worksheet.source_page - 1]
            return page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).tobytes("png")
    return Response(await asyncio.to_thread(render), media_type="image/png")

@app.get("/sessions/{key}/fields/{field_id}/eligibility/source")
async def eligibility_source(key: str, field_id: str):
    session = get_session(key)
    field = next((item for item in session.fields if item.field_id == field_id), None)
    if field is None or field.eligibility_workflow is None or session.document_type != "pdf":
        raise HTTPException(404, "Eligibility source is available for supported PDF workflows only.")
    def render():
        with pymupdf.open(stream=documents[key], filetype="pdf") as document:
            page = document[field.eligibility_workflow.source_page - 1]
            return page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).tobytes("png")
    return Response(await asyncio.to_thread(render), media_type="image/png")

@app.get("/sessions/{key}/fields/{field_id}/table-lookup/source")
async def table_lookup_source(key: str, field_id: str):
    session = get_session(key)
    field = next((item for item in session.fields if item.field_id == field_id), None)
    if field is None or field.table_lookup is None or session.document_type != "pdf":
        raise HTTPException(404, "Table source is available for supported PDF lookups only.")
    def render():
        with pymupdf.open(stream=documents[key], filetype="pdf") as document:
            page = document[field.table_lookup.source_page - 1]
            return page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).tobytes("png")
    return Response(await asyncio.to_thread(render), media_type="image/png")

@app.get("/sessions/{key}/fields/{field_id}/speech")
async def speech(
    key: str,
    field_id: str,
    node_id: str | None = None,
    eligibility_step: str | None = None,
):
    session = get_session(key)
    field = next((f for f in session.fields if f.field_id == field_id), None)
    if field is None:
        raise HTTPException(404, 'Field not found.')
    speech_text = field.simplified_question
    if node_id is not None:
        tree = field.decision_tree
        node = next((item for item in tree.nodes if item.node_id == node_id), None) if tree else None
        if node is None:
            raise HTTPException(404, 'Decision question not found.')
        speech_text = node.question
    if eligibility_step is not None:
        workflow = field.eligibility_workflow
        if workflow is None:
            raise HTTPException(404, "Eligibility workflow not found.")
        condition = next(
            (item for item in workflow.conditions if item.condition_id == eligibility_step),
            None,
        )
        if condition:
            speech_text = f"{condition.question} {condition.helper_text} {condition.unsure_help}"
        elif eligibility_step == "eligible":
            speech_text = f"{workflow.eligible_explanation} {workflow.certification_text}"
        elif eligibility_step == "ineligible":
            speech_text = workflow.ineligible_explanation
        else:
            raise HTTPException(404, "Eligibility explanation not found.")
    # Retain the session endpoint for compatibility; both UIs share the branch's provider logic.
    from .voice import SpeechRequest, speech as create_speech
    return await create_speech(SpeechRequest(text=speech_text))

@app.post("/sessions/{key}/fields/{field_id}", response_model=Session)
def answer(key: str, field_id: str, answer: Answer):
    session = get_session(key)
    if session.agent_state:
        raise HTTPException(409, "Use the agent answer tools or final review for this session.")
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

@app.post(
    "/sessions/{key}/fields/{field_id}/worksheet",
    response_model=WorksheetResult,
)
def calculate_field_worksheet(
    key: str,
    field_id: str,
    payload: WorksheetAnswers,
):
    session = get_session(key)
    field = next((item for item in session.fields if item.field_id == field_id), None)
    if field is None:
        raise HTTPException(404, "Field not found.")
    if field.worksheet is None:
        raise HTTPException(422, "This field does not have a supported worksheet.")
    try:
        value = calculate_worksheet(field.worksheet, payload.answers)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return WorksheetResult(value=float(value))

@app.post(
    "/sessions/{key}/fields/{field_id}/table-lookup",
    response_model=WorksheetResult,
)
def calculate_field_table_lookup(
    key: str,
    field_id: str,
    payload: TableLookupRequest,
):
    session = get_session(key)
    field = next((item for item in session.fields if item.field_id == field_id), None)
    if field is None:
        raise HTTPException(404, "Field not found.")
    if field.table_lookup is None:
        raise HTTPException(422, "This field does not have a supported table lookup.")
    try:
        value = lookup_wage_table(
            field.table_lookup,
            payload.filing_status,
            payload.higher_wage,
            payload.lower_wage,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return WorksheetResult(value=float(value))

@app.delete("/sessions/{key}")
def clear(key: str):
    sessions.pop(key, None)
    documents.pop(key, None)
    task = simplification_tasks.pop(key, None)
    if task:
        task.cancel()
    return {"cleared": True}

from .voice import router as voice_router
app.include_router(voice_router)

from .review import router as review_router
app.include_router(review_router)

from .agent_tools import router as agent_router
app.include_router(agent_router)
