"""Atomic final review and PDF download, independent of question conversation."""
import asyncio
import html
import json
import textwrap
from typing import Literal
from urllib.parse import quote

import pymupdf
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .documents import export_document

router = APIRouter()


class ReviewedAnswer(BaseModel):
    field_id: str
    value: str = Field(max_length=5000)


class ReviewedExport(BaseModel):
    reviewed: Literal[True]
    answers: list[ReviewedAnswer] = Field(max_length=100)


def validate_value(field, value):
    if not value.strip():
        return
    if field.answer_type in {'choice', 'checkbox'} and value not in field.options:
        raise HTTPException(422, 'Please choose one of the available options.')
    if field.answer_type == 'multichoice':
        try:
            selected = json.loads(value)
        except ValueError:
            raise HTTPException(422, 'Please choose from the available options.') from None
        if not isinstance(selected, list) or any(not isinstance(v, str) or v not in field.options for v in selected):
            raise HTTPException(422, 'Please choose from the available options.')


def answer_sheet_pdf(session):
    """A labeled answer sheet; never claim to reproduce or fill a Word/image form."""
    lines = []
    for index, field in enumerate(session.fields, 1):
        value = field.user_response or '[No answer provided]'
        if field.answer_type == 'multichoice' and field.user_response:
            value = ', '.join(json.loads(field.user_response)) or '[No answer provided]'
        source = 'Screenshot' if session.document_type == 'image' else 'Source page'
        reference = f'{source} {field.source_page}' if field.source_page > 0 else 'Source page not provided'
        content = f'{index}. {field.original_question}\n{reference}\nAnswer: {value}\n'
        for line in content.split('\n'):
            lines.extend(textwrap.wrap(line, width=78, break_long_words=True) or [''])
    with pymupdf.open() as document:
        for start in range(0, max(1, len(lines)), 36):
            page = document.new_page(width=595, height=842)
            content = html.escape('\n'.join(lines[start:start + 36]))
            page.insert_htmlbox(pymupdf.Rect(42, 40, 553, 795),
                '<h1>forma — answer sheet</h1><p>' + html.escape(session.filename) + '</p>'
                '<p>Use alongside your original form. The original document has not been filled.</p>'
                '<pre>' + content + '</pre>',
                css='body {font-family:sans-serif;font-size:11pt;} h1 {font-size:17pt;} pre {font-family:sans-serif;white-space:pre-wrap;}')
            page.insert_text((42, 820), f'Page {start // 36 + 1}', fontsize=9)
        return document.tobytes()


def reviewed_pdf(session, data):
    if session.document_type == 'pdf':
        return export_document(session, data)[0]
    return answer_sheet_pdf(session)


@router.post('/sessions/{key}/review/export')
async def export_review(key: str, body: ReviewedExport):
    from .main import get_session, sessions, documents
    original = get_session(key)
    before = original.model_dump()
    from .agent_tools import visible_fields, apply_review
    expected_fields = visible_fields(original) if original.agent_state else original.fields
    ids = [answer.field_id for answer in body.answers]
    if len(ids) != len(set(ids)) or set(ids) != {f.field_id for f in expected_fields}:
        raise HTTPException(422, 'Review must include each form field exactly once. Refresh and try again.')
    updated = original.model_copy(deep=True)
    values = {answer.field_id: answer.value for answer in body.answers}
    try:
        if updated.agent_state:
            apply_review(updated, values)
        for field in updated.fields:
            if field.field_id not in values:
                continue
            value = field.user_response if updated.agent_state else values[field.field_id]
            validate_value(field, value)
            field.user_response = field.interpreted_value = value
            field.confirmed = bool(value.strip())
            field.status = 'answered' if value.strip() else 'skipped'
    except HTTPException as error:
        from .languages import answer_error
        raise await answer_error(error, original.language) from None
    try:
        export_snapshot = updated.model_copy(update={'fields': visible_fields(updated)}) if updated.agent_state else updated
        pdf = await asyncio.to_thread(reviewed_pdf, export_snapshot, documents[key])
    except Exception:
        raise HTTPException(502, 'The PDF could not be created. Your edits are still here; please try again.') from None
    if get_session(key) is not original or original.model_dump() != before:
        raise HTTPException(409, 'This form changed during export. Refresh and review the latest answers.')
    sessions[key] = (sessions[key][0], updated)
    name = original.filename.rsplit('.', 1)[0]
    filename = f'formfriend-{name}.pdf' if original.document_type == 'pdf' else f'formfriend-{name}-answers.pdf'
    return Response(pdf, media_type='application/pdf', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename),
        'Cache-Control': 'no-store',
    })
