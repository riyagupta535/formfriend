from typing import Literal
from pydantic import BaseModel, Field

class FormField(BaseModel):
    field_id: str
    original_question: str
    simplified_question: str = ""
    answer_type: Literal["text", "number", "checkbox", "choice", "multichoice"] = "text"
    options: list[str] = Field(default_factory=list)
    widget_refs: list[str] = Field(default_factory=list)
    extraction: Literal["native", "printed"] = "native"
    source_page: int
    source_rect: list[float]
    user_response: str | None = None
    interpreted_value: str | None = None
    confirmed: bool = False
    status: Literal["unanswered", "answered", "skipped"] = "unanswered"

class Session(BaseModel):
    session_id: str
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
