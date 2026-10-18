from typing import Literal
from pydantic import BaseModel, Field, model_validator
from .agent_models import AgentState

class SubQuestion(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    helper_text: str | None = Field(default=None, max_length=500)
    answer_type: Literal["text", "number", "currency", "date", "checkbox", "choice"]
    options: list[str] = Field(default_factory=list)

class DecisionAnswer(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    next_node_id: str | None = Field(default=None, max_length=100)
    terminal_option: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def exactly_one_target(self):
        if (self.next_node_id is None) == (self.terminal_option is None):
            raise ValueError("A decision answer must have exactly one next node or terminal option.")
        return self

class DecisionNode(BaseModel):
    node_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=200)
    helper_text: str | None = Field(default=None, max_length=500)
    answers: list[DecisionAnswer] = Field(min_length=2, max_length=6)

class DecisionTree(BaseModel):
    start_node_id: str = Field(min_length=1, max_length=100)
    nodes: list[DecisionNode] = Field(min_length=1, max_length=10)

class CalculationSpec(BaseModel):
    operation: Literal["multiply", "add"]
    input_question_indices: list[int] = Field(default_factory=list, max_length=3)
    factor: float | None = Field(default=None, gt=0)
    source_question_numbers: list[str] = Field(default_factory=list, max_length=5)
    source_field_ids: list[str] = Field(default_factory=list, max_length=5)
    condition_question_index: int | None = Field(default=None, ge=0, le=2)
    condition_answer: str | None = Field(default=None, max_length=100)
    condition_zero_answers: list[str] = Field(default_factory=list, max_length=3)
    condition_skip_answers: list[str] = Field(default_factory=list, max_length=3)
    condition_failure_message: str | None = Field(default=None, max_length=500)

class WorksheetInput(BaseModel):
    input_id: str = Field(min_length=1, max_length=50)
    question: str = Field(min_length=1, max_length=300)
    helper_text: str | None = Field(default=None, max_length=1000)
    answer_type: Literal["currency", "choice"]
    options: list[str] = Field(default_factory=list, max_length=6)

class WorksheetExpression(BaseModel):
    operation: Literal[
        "input", "constant", "add", "subtract", "max", "multiply",
        "if_greater", "lookup",
    ]
    input_id: str | None = Field(default=None, max_length=50)
    value: float | None = None
    operands: list["WorksheetExpression"] = Field(default_factory=list, max_length=10)
    choices: dict[str, float] = Field(default_factory=dict)

class WorksheetSpec(BaseModel):
    worksheet_id: str = Field(min_length=1, max_length=100)
    task_label: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    source_page: int = Field(ge=1)
    result_line: str = Field(min_length=1, max_length=20)
    intro_question: str = Field(min_length=1, max_length=300)
    intro_helper_text: str = Field(min_length=1, max_length=1000)
    source_text: str = Field(min_length=1, max_length=15000)
    inputs: list[WorksheetInput] = Field(min_length=1, max_length=25)
    result_expression: WorksheetExpression

class WageRange(BaseModel):
    minimum: int = Field(ge=0)
    maximum: int | None = Field(default=None, ge=0)

class WageTableRow(WageRange):
    values: list[int] = Field(min_length=1, max_length=20)

class WageTable(BaseModel):
    filing_status: str = Field(min_length=1, max_length=100)
    columns: list[WageRange] = Field(min_length=1, max_length=20)
    rows: list[WageTableRow] = Field(min_length=1, max_length=30)

class TableLookupSpec(BaseModel):
    lookup_id: str = Field(min_length=1, max_length=100)
    source_page: int = Field(ge=1)
    intro_question: str = Field(min_length=1, max_length=300)
    intro_helper_text: str = Field(min_length=1, max_length=1000)
    higher_wage_label: str = Field(min_length=1, max_length=200)
    lower_wage_label: str = Field(min_length=1, max_length=200)
    tables: list[WageTable] = Field(min_length=1, max_length=6)

class AnnualAmountSource(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    source_field_id: str = Field(min_length=1, max_length=300)

class PayPeriodCalculationSpec(BaseModel):
    intro_question: str = Field(min_length=1, max_length=300)
    intro_helper_text: str = Field(min_length=1, max_length=1000)
    annual_amount_sources: list[AnnualAmountSource] = Field(min_length=2, max_length=4)
    pay_period_field_id: str = Field(min_length=1, max_length=300)

class EligibilityCondition(BaseModel):
    condition_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=300)
    helper_text: str = Field(min_length=1, max_length=1000)
    yes_label: str = Field(min_length=1, max_length=200)
    no_label: str = Field(min_length=1, max_length=200)
    unsure_label: str = Field(min_length=1, max_length=100)
    unsure_help: str = Field(min_length=1, max_length=1200)

class EligibilityWorkflow(BaseModel):
    workflow_id: str = Field(min_length=1, max_length=100)
    task_label: str = Field(min_length=1, max_length=100)
    source_page: int = Field(ge=1)
    source_section: str = Field(min_length=1, max_length=200)
    intro_question: str = Field(min_length=1, max_length=300)
    intro_helper_text: str = Field(min_length=1, max_length=1000)
    conditions: list[EligibilityCondition] = Field(min_length=1, max_length=5)
    eligible_explanation: str = Field(min_length=1, max_length=1200)
    ineligible_explanation: str = Field(min_length=1, max_length=1200)
    certification_text: str = Field(min_length=1, max_length=1200)
    checked_value: str = Field(min_length=1, max_length=20)
    source_text: str = Field(min_length=1, max_length=15000)

class FormField(BaseModel):
    field_id: str
    question_number: str | None = None
    section_title: str | None = None
    original_question: str
    simplified_question: str = ""
    helper_text: str | None = None
    subquestions: list["SubQuestion"] = Field(default_factory=list)
    calculation: CalculationSpec | None = None
    decision_tree: DecisionTree | None = None
    worksheet: WorksheetSpec | None = None
    table_lookup: TableLookupSpec | None = None
    pay_period_calculation: PayPeriodCalculationSpec | None = None
    eligibility_workflow: EligibilityWorkflow | None = None
    simplification_status: Literal["pending", "complete", "failed"] = "complete"
    simplification_confidence: Literal["high", "medium", "low"] = "low"
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
    mode: Literal["mock", "gemini", "step-5-preview"]
    simplification_status: Literal["pending", "running", "complete", "partial"] = "complete"
    fields: list[FormField]
    pdf_has_answer_sheet: bool = False
    warnings: list[str] = Field(default_factory=list)

class FieldSimplification(BaseModel):
    field_id: str = Field(min_length=1, max_length=300)
    plain_question: str = Field(min_length=1, max_length=300)
    helper_text: str | None = Field(default=None, max_length=500)
    subquestions: list[SubQuestion] = Field(default_factory=list, max_length=3)
    calculation: CalculationSpec | None = None
    decision_tree: DecisionTree | None = None
    confidence: Literal["high", "medium", "low"]

class SimplificationBatch(BaseModel):
    results: list[FieldSimplification]

class Simplified(BaseModel):
    """Compatibility model for callers that simplify one standalone question."""
    question: str = Field(min_length=1, max_length=1000)

class Answer(BaseModel):
    value: str = Field(max_length=5000)
    confirmed: bool = False

class WorksheetAnswers(BaseModel):
    answers: dict[str, str] = Field(max_length=25)

class WorksheetResult(BaseModel):
    value: float = Field(ge=0)

class TableLookupRequest(BaseModel):
    filing_status: str = Field(min_length=1, max_length=100)
    higher_wage: float = Field(ge=0)
    lower_wage: float = Field(ge=0)
