"""Deterministic form state for an externally configured ElevenLabs agent."""
import json
import math
import os
import re
import secrets
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from collections import Counter

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import ValidationError

from .agent_models import (AgentSessionRequest, AgentState, ExplainRequest, FromUploadRequest, GlossaryEntry,
                           SaveAgentAnswer, SkipAgentQuestion, Validation)
from .models import FormField, Session
from .dates import normalize_date
from .text_utils import strip_form_reference


def authorize(authorization: str | None = Header(default=None)):
    secret = os.getenv('AGENT_TOOL_SECRET')
    if secret and not secrets.compare_digest((authorization or '').encode(), ('Bearer ' + secret).encode()):
        raise HTTPException(401, 'Agent tool authentication required.')


router = APIRouter(prefix='/agent', tags=['agent tools'], dependencies=[Depends(authorize)])


def check_rules(question, value):
    """Apply only the closed validators supported by the backend."""
    rules = question.validation
    def fail(default):
        raise HTTPException(422, rules.message or default)

    if (question.input_type in {'number', 'currency'} or rules.kind in {'integer', 'decimal_number'}
            or rules.min is not None or rules.max is not None):
        try:
            numeric = Decimal(str(value))
        except (InvalidOperation, ValueError):
            fail('Enter a number using digits only, without words or extra text.')
        if not numeric.is_finite():
            fail('Enter a finite number.')
        if rules.kind == 'integer' and numeric != numeric.to_integral_value():
            fail('Enter a whole number without decimals.')
        if rules.min is not None and numeric < Decimal(str(rules.min)):
            fail(f'The amount must be at least {rules.min}. Check the number with the person.')
        if rules.max is not None and numeric > Decimal(str(rules.max)):
            fail(f'The amount must be at most {rules.max}. Check the number with the person.')

    if isinstance(value, str):
        if rules.min_length is not None and len(value) < rules.min_length:
            fail(f'The answer looks too short (needs at least {rules.min_length} characters). Ask again.')
        if rules.max_length is not None and len(value) > rules.max_length:
            fail(f'The answer is too long (at most {rules.max_length} characters). Ask for a shorter answer.')
        kind = rules.kind
        if kind == 'person_name' and (not re.search(r'[^\W\d_]', value) or re.search(r'\d', value)):
            fail("Enter a name using letters rather than numbers or unrelated text.")
        if kind == 'social_security_number' and not _valid_ssn(value):
            fail('Enter a 9-digit Social Security number in the format XXX-XX-XXXX.')
        if kind == 'employer_identification_number' and not re.fullmatch(r'\d{2}-?\d{7}', value):
            fail('Enter a 9-digit employer identification number in the format XX-XXXXXXX.')
        if kind == 'taxpayer_identification_number' and not (
            _valid_ssn(value) or re.fullmatch(r'\d{2}-?\d{7}', value)
        ):
            fail('Enter a valid 9-digit SSN or employer identification number.')
        if kind == 'email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            fail('Enter an email address with a name, @ sign, and domain.')
        if kind == 'phone_number':
            digits = re.sub(r'\D', '', value)
            if not re.fullmatch(r'\+?[\d\s().-]+(?:\s*(?:x|ext\.?)[\s\d]+)?', value, re.I) or not 10 <= len(digits) <= 15:
                fail('Enter a phone number with 10 to 15 digits.')
        if kind == 'us_postal_code' and not re.fullmatch(r'\d{5}(?:-\d{4})?', value):
            fail('Enter a 5-digit ZIP code, optionally followed by four more digits.')
        if kind == 'us_state_code' and not re.fullmatch(r'[A-Za-z]{2}', value):
            fail('Enter the two-letter state abbreviation.')
        if kind == 'year' and not re.fullmatch(r'\d{4}', value):
            fail('Enter a four-digit year.')
        if kind in {'past_date', 'future_date'}:
            parsed = date.fromisoformat(value)
            if kind == 'past_date' and parsed >= date.today():
                fail('Enter a date before today.')
            if kind == 'future_date' and parsed <= date.today():
                fail('Enter a date after today.')


def _valid_ssn(value: str) -> bool:
    match = re.fullmatch(r'(\d{3})-?(\d{2})-?(\d{4})', value)
    if not match:
        return False
    area, group, serial = match.groups()
    return area not in {'000', '666'} and not area.startswith('9') and group != '00' and serial != '0000'


def encoded(question, value):
    """Validate canonical types; uncertainty belongs in conversation, never in saved values."""
    result = _encoded(question, value)
    check_rules(question, result if question.input_type == 'date' else value.strip() if isinstance(value, str) else value)
    return result


def _encoded(question, value):
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
            value = normalize_date(value)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
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
    sync_source_simplifications(session)
    refresh_applicability(session)
    return [f for f in session.fields if f.status not in {'not_applicable', 'blocked'}]


def sync_source_simplifications(session):
    """Copy completed per-question Gemini results into a live guided session."""
    source_id = session.agent_state.source_simplification_session_id
    if not source_id:
        return None
    from .main import documents, sessions
    entry = sessions.get(source_id)
    if entry is None:
        session.agent_state.source_simplification_session_id = None
        return None
    source = entry[1]
    for question, target, source_field in zip(session.agent_state.questions, session.fields, source.fields):
        if source_field.simplification_status == 'complete':
            simplified = strip_form_reference(source_field.simplified_question or source_field.original_question)
            question.simplified_question = simplified
            question.help_text = source_field.helper_text or source_field.source_context[:2000]
            question.validation = source_field.validation.model_copy(deep=True)
            target.simplified_question = simplified
            target.helper_text = source_field.helper_text
            target.subquestions = [item.model_copy(deep=True) for item in source_field.subquestions]
            target.calculation = source_field.calculation.model_copy(deep=True) if source_field.calculation else None
            target.decision_tree = source_field.decision_tree.model_copy(deep=True) if source_field.decision_tree else None
            target.worksheet = source_field.worksheet.model_copy(deep=True) if source_field.worksheet else None
            target.table_lookup = source_field.table_lookup.model_copy(deep=True) if source_field.table_lookup else None
            target.pay_period_calculation = (source_field.pay_period_calculation.model_copy(deep=True)
                                             if source_field.pay_period_calculation else None)
            target.eligibility_workflow = (source_field.eligibility_workflow.model_copy(deep=True)
                                           if source_field.eligibility_workflow else None)
            target.validation = source_field.validation.model_copy(deep=True)
            target.simplification_status = 'complete'
            target.simplification_confidence = source_field.simplification_confidence
        elif source_field.simplification_status == 'failed':
            target.simplification_status = 'failed'
    if source.simplification_status in {'complete', 'partial'}:
        session.agent_state.source_simplification_session_id = None
        sessions.pop(source_id, None)
        documents.pop(source_id, None)
        return None
    return source


def next_question(session):
    source = sync_source_simplifications(session)
    fields = {f.field_id: f for f in session.fields}
    question = next((q for q in session.agent_state.questions if fields[q.id].status == 'unanswered'), None)
    blocked = [q.id for q in session.agent_state.questions if fields[q.id].status == 'blocked']
    waiting = False
    if question is not None and source is not None:
        index = session.agent_state.questions.index(question)
        waiting = source.fields[index].simplification_status == 'pending'
    question_payload = question.model_dump() if question else None
    if question is not None:
        field = fields[question.id]
        numeric_workflow = (
            (field.calculation and field.calculation.source_field_ids)
            or field.worksheet or field.table_lookup or field.pay_period_calculation
        )
        if numeric_workflow and question.input_type not in {'number', 'currency'}:
            # Guided calculations always produce a number. Repair old sessions
            # and noisy extraction results before choosing an input or validating.
            question.input_type = 'currency'
            question.validation = Validation(kind='decimal_number', min=0)
            field.answer_type = 'currency'
            field.validation = question.validation.model_copy(deep=True)
            question_payload = question.model_dump()
        subquestions = [item.model_dump() for item in field.subquestions]
        simplified_question = question.simplified_question
        help_text = question.help_text
        # Repair older cached/session results whose headline asks yes/no while the
        # actual form field needs an amount. Present the numeric question directly.
        if (question.input_type in {'number', 'currency'} and field.calculation is None
                and not (field.worksheet or field.table_lookup or field.pay_period_calculation
                         or field.eligibility_workflow)):
            numeric = next((item for item in field.subquestions
                            if item.answer_type in {'number', 'currency'}), None)
            if numeric is not None:
                simplified_question = strip_form_reference(numeric.text)
                help_text = numeric.helper_text or help_text
                subquestions = []
        question_payload.update({
            'simplified_question': simplified_question,
            'help_text': help_text,
            'subquestions': subquestions,
            'calculation': field.calculation.model_dump() if field.calculation else None,
            'decision_tree': field.decision_tree.model_dump() if field.decision_tree else None,
            'worksheet': field.worksheet.model_dump() if field.worksheet else None,
            'table_lookup': field.table_lookup.model_dump() if field.table_lookup else None,
            'pay_period_calculation': (field.pay_period_calculation.model_dump()
                                       if field.pay_period_calculation else None),
            'eligibility_workflow': (field.eligibility_workflow.model_dump()
                                     if field.eligibility_workflow else None),
        })
    return {
        'session_id': session.session_id,
        'revision': session.agent_state.revision,
        'status': 'loading' if waiting else 'question' if question else 'blocked' if blocked else 'complete',
        'question': question_payload,
        'prior_answers': {field.field_id: field.user_response or '' for field in session.fields},
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


def questions_from_fields(session):
    """Turn parsed upload fields into agent questions, until LLM question generation replaces this."""
    name_counts = Counter(name for field in session.fields for name in field.pdf_field_names)
    questions, used_ids = [], set()
    for index, field in enumerate(session.fields):
        key = field.field_id.replace('/', '_')[:120]
        if key in used_ids:
            key = f'{key[:110]}-{index}'
        used_ids.add(key)
        original = field.original_question.strip() or field.field_id
        # Mock simplification only adds "Please tell me:"; the agent rephrases questions itself.
        simplified = strip_form_reference(
            original if session.mode == 'mock' else (field.simplified_question.strip() or original)
        )
        input_type = 'boolean' if field.answer_type == 'checkbox' else field.answer_type
        unique_name = next((name for name in field.pdf_field_names if name_counts[name] == 1), None)
        questions.append({
            'id': key, 'original_text': original[:5000], 'simplified_question': simplified[:1000],
            'help_text': field.source_context[:2000], 'input_type': input_type, 'required': False,
            'options': field.options if input_type in {'choice', 'multichoice'} else [],
            'pdf_field_name': unique_name if session.document_type == 'pdf' else None,
            'validation': field.validation.model_dump(),
            'source_reference': {'page': field.source_page if field.source_page >= 1 else None,
                                 'section': field.section_title},
        })
    return questions


@router.post('/sessions/from-upload', operation_id='create_agent_session_from_upload')
async def create_agent_session_from_upload(body: FromUploadRequest):
    """Start a guided conversation for an uploaded document, replacing its upload session."""
    from .main import get_session, sessions, documents
    source = get_session(body.document_session_id)
    if source.agent_state is not None:
        raise HTTPException(409, 'This form already has a guided conversation.')
    try:
        request = AgentSessionRequest(questions=questions_from_fields(source), document_session_id=source.session_id)
    except ValidationError:
        raise HTTPException(422, 'This form could not be turned into guided questions.') from None
    created = await create_agent_session(request)
    guided = get_session(created['session_id'])
    # Printed fields and screenshots do not have native PDF widget names, so the
    # generic agent-session constructor cannot map their richer workflow metadata.
    # The from-upload path has an exact positional mapping and can preserve it.
    for target, original in zip(guided.fields, source.fields):
        target.subquestions = [item.model_copy(deep=True) for item in original.subquestions]
        target.calculation = original.calculation.model_copy(deep=True) if original.calculation else None
        target.decision_tree = original.decision_tree.model_copy(deep=True) if original.decision_tree else None
        target.worksheet = original.worksheet.model_copy(deep=True) if original.worksheet else None
        target.table_lookup = original.table_lookup.model_copy(deep=True) if original.table_lookup else None
        target.pay_period_calculation = (original.pay_period_calculation.model_copy(deep=True)
                                         if original.pay_period_calculation else None)
        target.eligibility_workflow = (original.eligibility_workflow.model_copy(deep=True)
                                       if original.eligibility_workflow else None)
    if source.simplification_status in {'pending', 'running'}:
        guided.agent_state.source_simplification_session_id = source.session_id
    else:
        sessions.pop(source.session_id, None)
        documents.pop(source.session_id, None)
    return next_question(guided)


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


@router.post('/sessions/{key}/explain', operation_id='explain_term')
async def explain_term(key: str, body: ExplainRequest):
    """Show and keep the agent's explanation of a hard term. Does not change answers or the revision."""
    session = get_agent_session(key)
    question, _ = find_question(session, body.question_id)
    entry = GlossaryEntry(term=body.term.strip(), explanation=body.explanation.strip(),
                          example=body.example.strip(), question_id=question.id)
    glossary = session.agent_state.glossary
    glossary[entry.term.lower()] = entry
    return {'saved': True, 'term': entry.term, 'glossary_size': len(glossary)}


@router.get('/sessions/{key}/glossary', operation_id='get_glossary')
async def get_glossary(key: str):
    """Words this person has learned so far, for a 'words you learned' panel."""
    return {'terms': [entry.model_dump() for entry in get_agent_session(key).agent_state.glossary.values()]}
