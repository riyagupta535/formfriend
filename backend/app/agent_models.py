"""The Step 5 question contract and typed ElevenLabs tool payloads."""
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

Scalar = StrictBool | StrictInt | StrictFloat | StrictStr | None
Value = StrictBool | StrictInt | StrictFloat | StrictStr | list[StrictStr]


class ShowIf(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: str = Field(min_length=1, max_length=128)
    operator: Literal['equals']
    value: Scalar


class SourceReference(BaseModel):
    model_config = ConfigDict(extra='ignore')
    page: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=300)


ValidationKind = Literal[
    'none',
    'person_name',
    'social_security_number',
    'employer_identification_number',
    'taxpayer_identification_number',
    'email',
    'phone_number',
    'us_postal_code',
    'street_address',
    'city_state_zip',
    'us_state_code',
    'integer',
    'decimal_number',
    'year',
    'past_date',
    'future_date',
]


class Validation(BaseModel):
    """Closed, deterministic answer rules selected during question generation."""
    model_config = ConfigDict(extra='forbid')
    kind: ValidationKind = 'none'
    min: StrictInt | StrictFloat | None = None
    max: StrictInt | StrictFloat | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=1)
    message: str | None = Field(default=None, max_length=500)

    @model_validator(mode='after')
    def validate_rules(self):
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError('validation.min cannot exceed validation.max.')
        if self.min_length is not None and self.max_length is not None and self.min_length > self.max_length:
            raise ValueError('validation.min_length cannot exceed validation.max_length.')
        return self


class AgentQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=128)
    original_text: str = Field(min_length=1, max_length=5000)
    simplified_question: str = Field(min_length=1, max_length=1000)
    input_type: Literal['boolean', 'text', 'number', 'currency', 'date', 'choice', 'multichoice', 'address']
    depends_on: list[str] = Field(default_factory=list, max_length=100)
    show_if: ShowIf | None = None
    required: bool = False
    pdf_field_name: str | None = Field(default=None, max_length=500)
    # Choice questions require their allowed values; optional for the supplied boolean schema.
    options: list[str] = Field(default_factory=list, max_length=100)
    help_text: str = Field(default='', max_length=2000)
    validation: Validation = Field(default_factory=Validation)
    source_reference: SourceReference | None = None
    # Hints for the explain tool: terms a person may not know. Empty means the question is plain enough.
    key_terms: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode='after')
    def validate_question(self):
        if not self.id.strip() or '/' in self.id:
            raise ValueError('Question IDs must be nonempty and cannot contain slashes.')
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError('Dependencies must be unique.')
        if self.show_if and self.show_if.field not in self.depends_on:
            raise ValueError('show_if.field must be listed in depends_on.')
        if len(self.options) != len(set(self.options)) or any(not option.strip() for option in self.options):
            raise ValueError('Options must be unique and nonempty.')
        if self.input_type in {'choice', 'multichoice'} and not self.options:
            raise ValueError('Choice questions require options.')
        text_kinds = {
            'person_name', 'social_security_number', 'employer_identification_number',
            'taxpayer_identification_number', 'email', 'phone_number',
            'us_postal_code', 'us_state_code', 'year', 'street_address', 'city_state_zip',
        }
        if self.validation.kind in text_kinds and self.input_type not in {'text', 'address'}:
            raise ValueError('This validation kind requires a text answer.')
        if self.validation.kind in {'integer', 'decimal_number'} and self.input_type not in {
            'text', 'number', 'currency'
        }:
            raise ValueError('This validation kind requires a numeric-compatible answer.')
        if self.validation.kind in {'past_date', 'future_date'} and self.input_type != 'date':
            raise ValueError('This validation kind requires a date answer.')
        if (self.validation.min is not None or self.validation.max is not None) and self.input_type not in {
            'text', 'number', 'currency'
        }:
            raise ValueError('Numeric limits require a numeric-compatible answer.')
        if (self.validation.min_length is not None or self.validation.max_length is not None) and self.input_type not in {
            'text', 'address'
        }:
            raise ValueError('Length limits require a text answer.')
        if self.show_if and isinstance(self.show_if.value, float) and not math.isfinite(self.show_if.value):
            raise ValueError('Conditions must use finite values.')
        return self


class AgentSessionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    questions: list[AgentQuestion] = Field(min_length=1, max_length=100)
    document_session_id: str | None = None

    @model_validator(mode='after')
    def validate_graph(self):
        by_id = {q.id: q for q in self.questions}
        if len(by_id) != len(self.questions):
            raise ValueError('Question IDs must be unique.')
        visiting, visited = set(), set()
        def visit(key):
            if key in visiting:
                raise ValueError('Question dependencies contain a cycle.')
            if key in visited:
                return
            visiting.add(key)
            for dependency in by_id[key].depends_on:
                if dependency not in by_id:
                    raise ValueError('A dependency refers to an unknown question.')
                visit(dependency)
            visiting.remove(key)
            visited.add(key)
        for key in by_id:
            visit(key)
        # A conditional's value must have the same type as its parent answer.
        for question in self.questions:
            if question.show_if:
                parent = by_id[question.show_if.field]
                value = question.show_if.value
                if parent.input_type == 'boolean' and type(value) is not bool:
                    raise ValueError('Boolean conditions require true or false.')
                if parent.input_type in {'number', 'currency'} and (type(value) not in {int, float}):
                    raise ValueError('Numeric conditions require a number.')
                if parent.input_type in {'text', 'choice', 'date', 'address'} and not isinstance(value, str):
                    raise ValueError('Text conditions require a string.')
                if parent.input_type == 'choice' and value not in parent.options:
                    raise ValueError('Condition value is not an available option.')
                if parent.input_type == 'multichoice':
                    raise ValueError('equals on multichoice dependencies is not supported.')
        return self


class AgentState(BaseModel):
    questions: list[AgentQuestion]
    revision: int = 0
    raw_responses: dict[str, str] = Field(default_factory=dict)
    glossary: dict[str, 'GlossaryEntry'] = Field(default_factory=dict)
    source_simplification_session_id: str | None = None


class GlossaryEntry(BaseModel):
    term: str
    explanation: str
    example: str = ''
    why_it_matters: str = ''
    question_id: str


class TeachRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question_id: str = Field(min_length=1, max_length=128)
    # What the person asked, in their words. Empty means "decide whether this question needs teaching".
    user_question: str = Field(default='', max_length=500)


class ExplainRequest(BaseModel):
    """An explanation written by the agent's own model, saved so the person can read it again."""
    model_config = ConfigDict(extra='forbid')
    question_id: str = Field(min_length=1, max_length=128)
    term: str = Field(min_length=1, max_length=200)
    explanation: str = Field(min_length=1, max_length=1200)
    example: str = Field(default='', max_length=600)


class FromUploadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_session_id: str = Field(min_length=1, max_length=64)


class SaveAgentAnswer(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question_id: str = Field(min_length=1, max_length=128)
    value: Value
    raw_response: str = Field(default='', max_length=5000)
    revision: int | None = Field(default=None, ge=0)


class SkipAgentQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question_id: str = Field(min_length=1, max_length=128)
    revision: int | None = Field(default=None, ge=0)


AgentState.model_rebuild()
