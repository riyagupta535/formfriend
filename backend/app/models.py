from typing import Literal
from pydantic import BaseModel, Field
from .agent_models import AgentState

class FormField(BaseModel):
    field_id: str
    question_number: str | None = None
    section_title: str | None = None
    original_question: str
    simplified_question: str = ""
    answer_type: Literal["text", "number", "currency", "date", "checkbox", "choice", "multichoice"] = "text"
    options: list[str] = Field(default_factory=list)
    widget_refs: list[str] = Field(default_factory=list)
    extraction: Literal["native", "printed"] = "native"
    pdf_field_names: list[str] = Field(default_factory=list)
    source_page: int
    source_rect: list[float]
    source_context: str = ""
    extraction_confidence: Literal["high", "medium", "low"] = "medium"
    source_kind: Literal["fillable", "text-layer", "ocr"] = "fillable"
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    user_response: str | None = None
    interpreted_value: str | None = None
    confirmed: bool = False
    status: Literal["unanswered", "answered", "skipped", "not_applicable", "blocked"] = "unanswered"

class Session(BaseModel):
    session_id: str
    agent_state: AgentState | None = None
    filename: str
    document_type: Literal["pdf", "docx", "image"] = "pdf"
    mode: Literal["mock", "step-5-preview"]
    fields: list[FormField]
    pdf_has_answer_sheet: bool = False
    warnings: list[str] = Field(default_factory=list)

class Simplified(BaseModel):
    question: str = Field(min_length=1, max_length=1000)

class Answer(BaseModel):
    value: str = Field(max_length=5000)
    confirmed: bool = False
