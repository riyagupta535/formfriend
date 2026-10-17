"""Deterministic form state for an externally configured ElevenLabs agent."""
import json
import math
import os
import secrets
import time
from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException

from .agent_models import AgentSessionRequest, AgentState, SaveAgentAnswer, SkipAgentQuestion
from .models import FormField, Session


def authorize(authorization: str | None = Header(default=None)):
    secret = os.getenv('AGENT_TOOL_SECRET')
    if secret and not secrets.compare_digest((authorization or '').encode(), ('Bearer ' + secret).encode()):
        raise HTTPException(401, 'Agent tool authentication required.')


router = APIRouter(prefix='/agent', tags=['agent tools'], dependencies=[Depends(authorize)])


def encoded(question, value):
    """Validate canonical types; uncertainty belongs in conversation, never in saved values."""
    kind = question.input_type
    if kind == 'boolean':
        if type(value) is not bool:
            raise HTTPException(422, 'A clear yes/no answer is needed. Send a JSON boolean, not guessed text.')
        return 'Yes' if value else 'No'
    if kind in {'number', 'currency'}:
        try:
            finite = type(value) in {int, float} and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise HTTPException(422, 'A finite numeric value is required. Ask for the amount if it is unclear.')
        return str(value)
    if kind == 'multichoice':
        if not isinstance(value, list) or not value or any(v not in question.options for v in value) or len(set(value)) != len(value):
            raise HTTPException(422, 'Choose one or more distinct available options, or skip if optional.')
        return json.dumps(value)
    if not isinstance(value, str) or not value.strip() or len(value) > 5000:
        raise HTTPException(422, 'A nonempty text answer of up to 5000 characters is required.')
    value = value.strip()
    if kind == 'choice' and value not in question.options:
        raise HTTPException(422, 'Choose an exact available option. Ask a follow-up if the choice is unclear.')
    if kind == 'date':
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, 'A full date in YYYY-MM-DD format is required. Ask for missing date parts.') from None
    return value


def decoded(question, value):
    if question.input_type == 'boolean':
        return value == 'Yes'
    if question.input_type in {'number', 'currency', 'multichoice'}:
        return json.loads(value)
    return value


def refresh_applicability(session):
    """Evaluate unknown dependencies separately from false conditions, in DAG order."""
    state = session.agent_state
    if state is None:
        return
    fields = {field.field_id: field for field in session.fields}
    questions = {q.id: q for q in state.questions}
    done = set()
    def evaluate(key):
        if key in done:
            return
        question, field = questions[key], fields[key]
        for dependency in question.depends_on:
            evaluate(dependency)
        status = None
        if question.show_if:
            parent = fields[question.show_if.field]
            if parent.status == 'not_applicable':
                status = 'not_applicable'
            elif parent.status == 'answered' and decoded(questions[parent.field_id], parent.user_response) != question.show_if.value:
                status = 'not_applicable'
        if status is None:
            if any(fields[key].status == 'not_applicable' for key in question.depends_on):
                status = 'not_applicable'
            elif any(fields[key].status != 'answered' for key in question.depends_on):
                status = 'blocked'
        if status:
            field.status = status
            field.user_response = field.interpreted_value = None
            field.confirmed = False
        elif field.status in {'not_applicable', 'blocked'}:
            field.status = 'unanswered'
        done.add(key)
    for key in questions:
        evaluate(key)


def get_agent_session(key):
    from .main import get_session
    session = get_session(key)
    if session.agent_state is None:
        raise HTTPException(409, 'This session has no Step 5 question list. Create an agent session first.')
    refresh_applicability(session)
    return session


def visible_fields(session):
    refresh_applicability(session)
    return [f for f in session.fields if f.status not in {'not_applicable', 'blocked'}]


def next_question(session):
    fields = {f.field_id: f for f in session.fields}
    question = next((q for q in session.agent_state.questions if fields[q.id].status == 'unanswered'), None)
    blocked = [q.id for q in session.agent_state.questions if fields[q.id].status == 'blocked']
    return {
        'session_id': session.session_id,
        'revision': session.agent_state.revision,
        'status': 'question' if question else 'blocked' if blocked else 'complete',
        'question': question.model_dump() if question else None,
        'blocked_question_ids': blocked,
        'progress': {status: sum(f.status == status for f in session.fields)
                     for status in ['answered', 'unanswered', 'skipped', 'not_applicable', 'blocked']},
        'review_url': '/review' if not question and not blocked else None,
    }


def find_question(session, key):
    question = next((q for q in session.agent_state.questions if q.id == key), None)
    if question is None:
        raise HTTPException(404, 'Question not found.')
    return question, next(f for f in session.fields if f.field_id == key)


def check_revision(session, revision):
    if revision is not None and revision != session.agent_state.revision:
        raise HTTPException(409, 'The answers changed. Get the next question again before saving.')


def invalidate_dependents(session, key):
    changed = {key}
    while True:
        affected = {q.id for q in session.agent_state.questions if set(q.depends_on) & changed}
        if affected <= changed:
            break
        changed |= affected
    invalidated = []
    for field in session.fields:
        if field.field_id in changed - {key}:
            if field.status in {'answered', 'skipped'}:
                invalidated.append(field.field_id)
            field.status = 'unanswered'
            field.user_response = field.interpreted_value = None
            field.confirmed = False
            session.agent_state.raw_responses.pop(field.field_id, None)
    return invalidated


@router.post('/sessions', operation_id='create_agent_session')
async def create_agent_session(body: AgentSessionRequest):
    from .main import get_session, sessions, documents, prune
    prune()
    if len(sessions) >= 50:
        raise HTTPException(503, 'Demo is busy. Please try again shortly.')
    source = get_session(body.document_session_id) if body.document_session_id else None
    if source and source.agent_state is not None:
        raise HTTPException(409, 'Use an original document session when attaching a question list.')
    fields, used_refs = [], set()
    for question in body.questions:
        matches = [f for f in source.fields if question.pdf_field_name and
                   question.pdf_field_name in f.pdf_field_names] if source else []
        if question.pdf_field_name and source and source.document_type == 'pdf' and len(matches) != 1:
            raise HTTPException(422, 'A PDF field name did not map uniquely to the uploaded document.')
        if matches:
            original = matches[0]
            if original.field_id in used_refs:
                raise HTTPException(422, 'Multiple questions cannot map to the same parsed PDF field.')
            used_refs.add(original.field_id)
            field = original.model_copy(deep=True)
            field.widget_refs = original.widget_refs or [original.field_id]
            field.field_id = question.id
            field.user_response = field.interpreted_value = None
            field.confirmed = False
            field.status = 'unanswered'
            # Preserve native widget types and options so PDF export remains reliable.
            compatible = question.input_type == 'boolean' and field.answer_type == 'checkbox' or question.input_type == field.answer_type
            if not compatible and (field.answer_type != 'text' or question.input_type == 'multichoice'):
                raise HTTPException(422, 'Question input type conflicts with the mapped PDF control.')
            if question.input_type in {'choice', 'multichoice'} and question.options != field.options:
                raise HTTPException(422, 'Question options conflict with the mapped PDF control.')
        else:
            kind = 'choice' if question.input_type == 'boolean' else 'text' if question.input_type == 'address' else question.input_type
            field = FormField(field_id=question.id, original_question=question.original_text,
                answer_type=kind, options=['Yes', 'No'] if question.input_type == 'boolean' else question.options,
                source_page=0, source_rect=[], extraction='printed', source_kind='text-layer')
        if field.answer_type == 'text':
            field.answer_type = 'choice' if question.input_type == 'boolean' else 'text' if question.input_type == 'address' else question.input_type
            field.options = ['Yes', 'No'] if question.input_type == 'boolean' else question.options
        field.original_question = question.original_text
        field.simplified_question = question.simplified_question
        fields.append(field)
    key = uuid4().hex
    session = Session(session_id=key, filename=source.filename if source else 'form-answers',
        document_type=source.document_type if source else 'image', mode='step-5-preview', fields=fields,
        agent_state=AgentState(questions=body.questions),
        pdf_has_answer_sheet=any(f.extraction == 'printed' for f in fields),
        warnings=['Review all answers before exporting. Questions without a PDF mapping use an answer sheet.'])
    refresh_applicability(session)
    sessions[key] = (time.monotonic(), session)
    documents[key] = documents[source.session_id] if source else b''
    return next_question(session)


@router.get('/sessions/{key}/next-question', operation_id='get_next_question')
async def get_next_question(key: str):
    return next_question(get_agent_session(key))


@router.get('/sessions/{key}/questions/{question_id}/context', operation_id='get_question_context')
async def get_question_context(key: str, question_id: str):
    session = get_agent_session(key)
    question, field = find_question(session, question_id)
    return {'question': question.model_dump(), 'status': field.status,
            'answer': decoded(question, field.user_response) if field.status == 'answered' else None,
            'dependency_answers': {q.id: decoded(q, f.user_response)
                for q in session.agent_state.questions for f in session.fields
                if q.id in question.depends_on and f.field_id == q.id and f.status == 'answered'},
            'source_page': field.source_page if field.source_rect else None,
            'revision': session.agent_state.revision}


@router.post('/sessions/{key}/answers', operation_id='save_answer')
async def save_answer(key: str, body: SaveAgentAnswer):
    session = get_agent_session(key)
    check_revision(session, body.revision)
    question, field = find_question(session, body.question_id)
    if field.status in {'blocked', 'not_applicable'}:
        raise HTTPException(409, 'This question is not currently applicable. Get the next question first.')
    value = encoded(question, body.value)
    invalidated = invalidate_dependents(session, question.id) if field.user_response != value else []
    field.user_response = field.interpreted_value = value
    field.confirmed = False
    field.status = 'answered'
    session.agent_state.raw_responses[question.id] = body.raw_response
    session.agent_state.revision += 1
    refresh_applicability(session)
    return {'saved': True, 'question_id': question.id, 'value': decoded(question, value),
            'invalidated_question_ids': invalidated, 'next': next_question(session)}


@router.post('/sessions/{key}/skip', operation_id='skip_question')
async def skip_question(key: str, body: SkipAgentQuestion):
    session = get_agent_session(key)
    check_revision(session, body.revision)
    question, field = find_question(session, body.question_id)
    if question.required:
        raise HTTPException(422, 'This question is required. Offer an explanation or a follow-up instead of skipping.')
    if field.status in {'blocked', 'not_applicable'}:
        raise HTTPException(409, 'This question is not currently applicable.')
    invalidated = invalidate_dependents(session, question.id)
    field.user_response = field.interpreted_value = None
    field.status = 'skipped'
    field.confirmed = False
    session.agent_state.raw_responses.pop(question.id, None)
    session.agent_state.revision += 1
    refresh_applicability(session)
    return {'skipped': True, 'question_id': question.id, 'invalidated_question_ids': invalidated,
            'next': next_question(session)}


def apply_review(session, answers):
    """Validate review edits against the same typed schema as agent answers."""
    current_ids = {f.field_id for f in visible_fields(session)}
    changed = []
    for question in session.agent_state.questions:
        if question.id not in answers:
            continue
        field = next(f for f in session.fields if f.field_id == question.id)
        value = answers[question.id]
        if not value.strip():
            if question.required:
                raise HTTPException(422, 'Complete required questions before exporting.')
            encoded_value = ''
        else:
            if question.input_type == 'boolean':
                if value not in {'Yes', 'No'}:
                    raise HTTPException(422, 'Choose Yes or No for boolean answers.')
                typed = value == 'Yes'
            elif question.input_type in {'number', 'currency', 'multichoice'}:
                try:
                    typed = json.loads(value)
                except ValueError:
                    raise HTTPException(422, 'A reviewed answer has an invalid format.') from None
            else:
                typed = value
            encoded_value = encoded(question, typed)
        if (field.user_response or '') != encoded_value:
            changed.append(question.id)
        field.user_response = field.interpreted_value = encoded_value
        field.status = 'answered' if encoded_value else 'skipped'
        field.confirmed = bool(encoded_value)
    # Do not silently accept answers dependent on newly edited parent values.
    affected = set()
    for key in changed:
        affected.update(invalidate_dependents(session, key))
    refresh_applicability(session)
    if affected or {f.field_id for f in visible_fields(session)} != current_ids:
        raise HTTPException(409, 'This edit changes dependent questions. Update it in the guided conversation, then review again.')
    if any(f.status == 'blocked' for f in session.fields):
        raise HTTPException(422, 'Resolve the unanswered dependency questions before exporting.')
    session.agent_state.revision += 1
