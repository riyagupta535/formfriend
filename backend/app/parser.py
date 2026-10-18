from collections import defaultdict
from dataclasses import dataclass
import re

import pymupdf

from .models import (
    CalculationSpec,
    AnnualAmountSource,
    EligibilityCondition,
    EligibilityWorkflow,
    FormField,
    PayPeriodCalculationSpec,
    TableLookupSpec,
    WageRange,
    WageTable,
    WageTableRow,
    WorksheetExpression,
    WorksheetInput,
    WorksheetSpec,
)


@dataclass
class _Line:
    text: str
    rect: pymupdf.Rect
    block_number: int
    line_number: int


@dataclass
class _ExtractedWidget:
    xref: int
    name: str
    field_type: int
    label: str
    context: str
    rect: pymupdf.Rect
    page_number: int
    confidence: str


@dataclass
class _TextBlock:
    text: str
    rect: pymupdf.Rect
    block_number: int


_SUPPORTED_TYPES = {
    pymupdf.PDF_WIDGET_TYPE_TEXT,
    pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
    pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
    pymupdf.PDF_WIDGET_TYPE_LISTBOX,
}
_INTERNAL_NAME = re.compile(r"(?:^|\.)(?:f|c)\d+_\d+\[\d+\]$", re.IGNORECASE)
_NUMBERED_PROMPT = re.compile(r"^(\d+[a-z]?)[.)]?\s+(.+)", re.IGNORECASE)
_WORKSHEET_PAGE_REFERENCE = re.compile(
    r"(?:the\s+)?([A-Za-z][A-Za-z 0-9()/-]*?Worksheet)\s+on\s+page\s+(\d+)",
    re.IGNORECASE,
)

_W4_WAGE_TABLE_HEADINGS = (
    "Married Filing Jointly or Qualifying Surviving Spouse",
    "Single or Married Filing Separately",
    "Head of Household",
)
_W4_WAGE_COLUMNS = tuple(
    (start, start + 9999) for start in range(0, 120000, 10000)
)


def _money_number(text: str) -> int:
    return int(re.sub(r"[^0-9]", "", text))


def _w4_wage_tables(page: pymupdf.Page) -> list[WageTable]:
    """Extract the official wage lookup grids from the referenced W-4 page."""
    heading_rects = []
    for heading in _W4_WAGE_TABLE_HEADINGS:
        matches = page.search_for(heading)
        if not matches:
            return []
        heading_rects.append((heading, matches[0]))

    words = page.get_text("words", sort=True)
    tables: list[WageTable] = []
    columns = [WageRange(minimum=low, maximum=high) for low, high in _W4_WAGE_COLUMNS]
    for index, (heading, rect) in enumerate(heading_rects):
        section_end = (
            heading_rects[index + 1][1].y0 if index + 1 < len(heading_rects)
            else page.rect.height
        )
        grouped: dict[float, list[tuple]] = defaultdict(list)
        for word in words:
            if rect.y1 + 45 <= word[1] < section_end:
                # A few printed cells sit a fraction of a point off their row baseline.
                grouped[round(word[1] / 2) * 2].append(word)

        rows: list[WageTableRow] = []
        for row_words in grouped.values():
            cells = sorted(row_words, key=lambda word: word[0])
            value_words = [word for word in cells if word[0] >= 115 and re.fullmatch(r"\$?[\d,]+", word[4])]
            label_words = [word[4] for word in cells if word[0] < 115]
            if len(value_words) != len(columns):
                continue
            bounds = [_money_number(token) for token in label_words if re.search(r"\d", token)]
            if not bounds:
                continue
            maximum = None if any(token.lower() == "over" for token in label_words) else bounds[-1]
            rows.append(WageTableRow(
                minimum=bounds[0],
                maximum=maximum,
                values=[_money_number(word[4]) for word in value_words],
            ))
        if len(rows) < 10:
            return []
        tables.append(WageTable(filing_status=heading, columns=columns, rows=rows))
    return tables


def _attach_table_lookup_workflows(
    document: pymupdf.Document,
    fields: list[FormField],
) -> None:
    table_fields = [
        field for field in fields
        if "appropriate table on page" in f"{field.original_question} {field.source_context}".lower()
        and "higher paying job" in f"{field.original_question} {field.source_context}".lower()
        and "lower paying job" in f"{field.original_question} {field.source_context}".lower()
    ]
    if not table_fields:
        return
    source_page = 5
    if len(document) < source_page:
        return
    tables = _w4_wage_tables(document[source_page - 1])
    if len(tables) != len(_W4_WAGE_TABLE_HEADINGS):
        return
    for field in table_fields:
        evidence = f"{field.original_question} {field.source_context}".lower()
        combined = "add the annual wages of the two highest" in evidence
        field.table_lookup = TableLookupSpec(
            lookup_id=f"w4-multiple-jobs-{field.field_id}",
            source_page=source_page,
            intro_question="Let’s calculate the amount from the wage table for you.",
            intro_helper_text=(
                "Answer three questions and Form Friend will find the matching amount. "
                "You do not need to read the table yourself."
            ),
            higher_wage_label=(
                "What are the combined annual wages from your two highest-paying jobs?"
                if combined else "What are the annual wages from the higher-paying job?"
            ),
            lower_wage_label=(
                "What are the annual wages from the third job?"
                if combined else "What are the annual wages from the lower-paying job?"
            ),
            tables=tables,
        )

    sum_field = next(
        (
            field for field in fields
            if "add the amounts from lines 2a and 2b" in
            f"{field.original_question} {field.source_context}".lower()
        ),
        None,
    )
    three_job_lookups = [
        field for field in table_fields
        if field.source_page == sum_field.source_page
    ] if sum_field else []
    if sum_field is not None and len(three_job_lookups) >= 3:
        # The first lookup is the separate two-job path. The next two are the
        # amounts the three-job total explicitly tells the user to add.
        sources = three_job_lookups[-2:]
        sum_field.calculation = CalculationSpec(
            operation="add",
            input_question_indices=[],
            factor=None,
            source_question_numbers=[],
            source_field_ids=[field.field_id for field in sources],
            condition_question_index=None,
            condition_answer=None,
            condition_zero_answers=[],
            condition_skip_answers=[],
            condition_failure_message=None,
        )
        sum_field.simplified_question = "Let’s add the two wage-table amounts."
        sum_field.helper_text = (
            "Form Friend will use the two amounts calculated in the previous questions."
        )
        sum_field.simplification_status = "complete"
        sum_field.simplification_confidence = "high"

        pay_period_field = next(
            (
                field for field in fields
                if field.source_page == sum_field.source_page
                and "number of pay periods per year" in
                f"{field.original_question} {field.source_context}".lower()
            ),
            None,
        )
        final_field = next(
            (
                field for field in fields
                if field.source_page == sum_field.source_page
                and "divide the annual amount" in
                f"{field.original_question} {field.source_context}".lower()
            ),
            None,
        )
        if pay_period_field is not None and final_field is not None:
            final_field.pay_period_calculation = PayPeriodCalculationSpec(
                intro_question="Let’s calculate the extra withholding for each paycheck.",
                intro_helper_text=(
                    "Form Friend will use your wage-table result and pay frequency to calculate this amount."
                ),
                annual_amount_sources=[
                    AnnualAmountSource(
                        label="I have two jobs total",
                        source_field_id=three_job_lookups[0].field_id,
                    ),
                    AnnualAmountSource(
                        label="I have three jobs total",
                        source_field_id=sum_field.field_id,
                    ),
                ],
                pay_period_field_id=pay_period_field.field_id,
            )
            final_field.simplified_question = final_field.pay_period_calculation.intro_question
            final_field.helper_text = final_field.pay_period_calculation.intro_helper_text
            final_field.simplification_status = "complete"
            final_field.simplification_confidence = "high"


def _worksheet_expression(
    operation: str,
    *operands: WorksheetExpression,
    input_id: str | None = None,
    value: float | None = None,
    choices: dict[str, float] | None = None,
) -> WorksheetExpression:
    return WorksheetExpression(
        operation=operation,
        input_id=input_id,
        value=value,
        operands=list(operands),
        choices=choices or {},
    )


def _w4_deductions_workflow(page_text: str, page_number: int) -> WorksheetSpec | None:
    """Build the supported worksheet only when every formula anchor is in the PDF."""
    compact = re.sub(r"\s+", " ", page_text)
    required = (
        "Deductions Worksheet",
        "Add lines 1a, 1b, and 1c",
        "Add lines 3a and 3b",
        "Add lines 6a, 6b, 6c, 6d, and 6e",
        "multiply line 7 by 94% (0.94)",
        "Add lines 2, 4, 5, and 14",
        "enter the result here and in Step 4(b)",
        "$768,700", "$640,600", "$384,350",
        "$32,200", "$24,150", "$16,100", "$6,000",
    )
    if any(anchor.lower() not in compact.lower() for anchor in required):
        return None

    ref = lambda name: _worksheet_expression("input", input_id=name)
    constant = lambda value: _worksheet_expression("constant", value=value)
    add = lambda *items: _worksheet_expression("add", *items)
    subtract = lambda left, right: _worksheet_expression("subtract", left, right)
    multiply = lambda item, factor: _worksheet_expression("multiply", item, constant(factor))
    maximum = lambda *items: _worksheet_expression("max", *items)
    if_greater = lambda left, right, yes, no: _worksheet_expression(
        "if_greater", left, right, yes, no
    )
    lookup = lambda name, choices: _worksheet_expression(
        "lookup", input_id=name, choices=choices
    )

    line_2 = add(ref("1a"), ref("1b"), ref("1c"))
    line_4 = add(
        lookup("3a", {"Yes": 6000, "No": 0}),
        lookup("3b", {"Yes": 6000, "No": 0}),
    )
    line_7 = add(ref("6a"), ref("6b"), ref("6c"), ref("6d"), ref("6e"))
    line_8b = maximum(subtract(ref("8a"), line_4), constant(0))
    line_9 = lookup("filing_status", {
        "Single": 640600,
        "Married filing jointly or qualifying surviving spouse": 768700,
        "Head of household": 640600,
        "Married filing separately": 384350,
    })
    line_10 = if_greater(line_9, line_8b, line_7, multiply(line_7, .94))
    line_11 = lookup("filing_status", {
        "Single": 16100,
        "Married filing jointly or qualifying surviving spouse": 32200,
        "Head of household": 24150,
        "Married filing separately": 16100,
    })
    line_13 = add(line_11, ref("12"))
    line_14 = if_greater(
        line_10,
        line_13,
        subtract(line_10, line_11),
        ref("12"),
    )
    line_15 = add(line_2, line_4, ref("5"), line_14)

    currency = lambda input_id, question, helper: WorksheetInput(
        input_id=input_id,
        question=question,
        helper_text=helper,
        answer_type="currency",
    )
    inputs = [
        currency("1a", "What is your estimated amount of qualified tips?", "Enter 0 if this does not apply. The worksheet limits this amount based on income and caps it at $25,000."),
        currency("1b", "What is your estimated qualified overtime amount?", "Use only the extra half of time-and-a-half compensation. Enter 0 if this does not apply."),
        currency("1c", "What is your estimated qualified passenger vehicle loan interest?", "Enter eligible interest up to the worksheet limit, or 0 if this does not apply."),
        WorksheetInput(input_id="3a", question="Will you be age 65 or older before the end of the year?", helper_text="Choose Yes only if the worksheet's income limit also applies to you.", answer_type="choice", options=["Yes", "No"]),
        WorksheetInput(input_id="3b", question="Will your spouse be age 65 or older and have a Social Security number valid for employment?", helper_text="Choose Yes only if the worksheet's income limit also applies and you are including a spouse.", answer_type="choice", options=["Yes", "No"]),
        currency("5", "What is your estimated total for income adjustments?", "This may include student loan interest, deductible IRA contributions, educator expenses, alimony paid, and certain other income adjustments. Enter 0 if none apply."),
        currency("6a", "How much can you claim for medical and dental expenses?", "Include only qualifying expenses above 7.5% of your total income. Enter 0 if none apply."),
        currency("6b", "How much can you claim for state and local taxes?", "Use the amount allowed by the income and filing-status limits in the worksheet, or enter 0."),
        currency("6c", "How much eligible home mortgage interest can you claim?", "Use eligible home mortgage interest under the debt limits in the worksheet, or enter 0."),
        currency("6d", "How much can you claim for charitable gifts?", "Include only qualifying contributions above 0.5% of your total income. Enter 0 if none apply."),
        currency("6e", "How much can you claim for other itemized deductions?", "Enter other eligible itemized deductions, or 0 if none apply."),
        currency("8a", "What is your estimated total income?", "This is used only to apply the worksheet's itemized-deduction limitation."),
        WorksheetInput(input_id="filing_status", question="What filing status will you use?", helper_text="This selects the exact thresholds printed on the worksheet.", answer_type="choice", options=["Single", "Married filing jointly or qualifying surviving spouse", "Head of household", "Married filing separately"]),
        currency("12", "If you take the standard deduction, how much eligible cash giving will you claim?", "Enter qualifying cash gifts within the worksheet limit, or 0 if this does not apply."),
    ]
    return WorksheetSpec(
        worksheet_id="w4-step-4b-deductions-2026",
        task_label="DEDUCTIONS",
        title="Deductions Worksheet",
        source_page=page_number,
        result_line="15",
        intro_question="Would you like help figuring out whether to enter an amount for deductions?",
        intro_helper_text=(
            "Deductions can affect how much federal income tax is taken out of your paycheck. "
            "You can leave this field blank if you don't want to claim additional deductions here."
        ),
        source_text=page_text[:15000],
        inputs=inputs,
        result_expression=line_15,
    )


def _attach_worksheet_workflows(document: pymupdf.Document, fields: list[FormField]) -> None:
    dependent_pages: set[int] = set()
    for field in fields:
        evidence = f"{field.original_question} {field.source_context}"
        match = _WORKSHEET_PAGE_REFERENCE.search(evidence)
        if not match:
            continue
        page_number = int(match.group(2))
        if not 1 <= page_number <= len(document):
            continue
        page_text = document[page_number - 1].get_text("text", sort=True)
        worksheet = _w4_deductions_workflow(page_text, page_number)
        if worksheet is not None:
            field.worksheet = worksheet
            dependent_pages.add(page_number)
    if dependent_pages:
        # Worksheet lines are subtasks of the referring field, not separate top-level tasks.
        fields[:] = [
            field for field in fields
            if field.worksheet is not None or field.source_page not in dependent_pages
        ]


def _w4_exemption_workflow(
    page_text: str,
    page_number: int,
    checked_value: str,
) -> EligibilityWorkflow | None:
    compact = re.sub(r"\s+", " ", page_text)
    required = (
        "Exemption from withholding",
        "no federal income tax liability in 2025",
        "expect to have no federal income tax liability in 2026",
        "line 24 on your 2025 Form 1040",
        "lines 27a, 28, 29, and 30",
        "you will have no income tax withheld",
        "may owe taxes and penalties",
        "complete Steps 1(a)",
        "1(b), and 5",
        "new Form W-4 by February 16, 2027",
    )
    if any(anchor.lower() not in compact.lower() for anchor in required):
        return None
    return EligibilityWorkflow(
        workflow_id="w4-exempt-2026",
        task_label="TAX WITHHOLDING EXEMPTION",
        source_page=page_number,
        source_section="Exemption from withholding",
        intro_question="Let’s check whether you qualify for exemption from federal income tax withholding.",
        intro_helper_text=(
            "Exemption means your employer will not withhold federal income tax from your pay. "
            "Wanting less tax withheld does not by itself make you eligible."
        ),
        conditions=[
            EligibilityCondition(
                condition_id="no_2025_liability",
                question="Did you have zero federal income tax liability for 2025?",
                helper_text=(
                    "This means the federal income tax you were legally responsible for—not whether "
                    "you received a refund or had tax taken from your pay."
                ),
                yes_label="Yes, I had zero federal income tax liability",
                no_label="No, I had federal income tax liability",
                unsure_label="I'm not sure",
                unsure_help=(
                    "Look at the total tax and refundable-credit amounts on your 2025 Form 1040 "
                    "or 1040-SR. You may have had no tax liability if your total tax was zero or "
                    "was fully offset by the applicable refundable credits. You may also meet this "
                    "condition if you did not have to file because your income was below the filing threshold."
                ),
            ),
            EligibilityCondition(
                condition_id="expect_no_2026_liability",
                question="Do you expect to have zero federal income tax liability for 2026?",
                helper_text=(
                    "Answer based on the federal income tax you expect to be legally responsible for "
                    "in 2026—not whether you expect a refund."
                ),
                yes_label="Yes, I expect zero federal income tax liability",
                no_label="No, I expect federal income tax liability",
                unsure_label="I'm not sure",
                unsure_help=(
                    "Review your expected 2026 income, deductions, and credits before certifying. "
                    "Leave the exemption box unchecked until you can confirm that your expected "
                    "federal income tax liability is zero."
                ),
            ),
        ],
        eligible_explanation=(
            "Both required conditions are satisfied. If you claim exemption, no federal income tax "
            "will be withheld from your paycheck. You may owe tax and penalties if this certification "
            "is incorrect. Follow the form's instructions for claiming exemption and submit a new W-4 for 2027."
        ),
        ineligible_explanation=(
            "You cannot claim exemption because both required conditions must be true. "
            "Form Friend will leave the exemption box unchecked."
        ),
        certification_text=(
            "I certify that I had no federal income tax liability in 2025 and expect to have no "
            "federal income tax liability in 2026."
        ),
        checked_value=checked_value,
        source_text=page_text[:15000],
    )


def _attach_eligibility_workflows(
    document: pymupdf.Document,
    fields: list[FormField],
) -> None:
    checked_values_by_name: dict[str, str] = {}
    for page in document:
        for widget in page.widgets() or []:
            if widget.field_name and widget.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                checked_values_by_name[widget.field_name] = str(widget.on_state() or "Yes")
    for field in fields:
        evidence = f"{field.original_question} {field.source_context}".lower()
        if (
            field.answer_type != "checkbox"
            or "claim exemption from withholding for 2026" not in evidence
        ):
            continue
        page_match = re.search(r"page\s+(\d+)", evidence)
        if not page_match:
            continue
        page_number = int(page_match.group(1))
        if not 1 <= page_number <= len(document):
            continue
        checked_value = next(
            (checked_values_by_name[name] for name in field.pdf_field_names
             if name in checked_values_by_name),
            "Yes",
        )
        field.eligibility_workflow = _w4_exemption_workflow(
            document[page_number - 1].get_text("text", sort=True),
            page_number,
            checked_value,
        )


def _clean_tokens(tokens: list[str]) -> str:
    useful = [token for token in tokens if token.strip() not in {".", "..", "..."}]
    return re.sub(r"\s+", " ", " ".join(useful)).strip(" .")


def _logical_lines(page: pymupdf.Page) -> list[_Line]:
    grouped: dict[tuple[int, int], list[tuple]] = defaultdict(list)
    for word in page.get_text("words", sort=True):
        grouped[(word[5], word[6])].append(word)

    lines = []
    for (block_number, line_number), words in grouped.items():
        text = _clean_tokens([word[4] for word in words])
        if not text:
            continue
        lines.append(_Line(
            text=text,
            rect=pymupdf.Rect(
                min(word[0] for word in words), min(word[1] for word in words),
                max(word[2] for word in words), max(word[3] for word in words),
            ),
            block_number=block_number,
            line_number=line_number,
        ))
    return sorted(lines, key=lambda line: (line.rect.y0, line.rect.x0))


def _visual_lines(page: pymupdf.Page) -> list[_Line]:
    rows: list[list[tuple]] = []
    for word in page.get_text("words", sort=True):
        center = (word[1] + word[3]) / 2
        row = next((candidate for candidate in rows
                    if abs(((candidate[0][1] + candidate[0][3]) / 2) - center) <= 2.5), None)
        if row is None:
            rows.append([word])
        else:
            row.append(word)

    lines = []
    for index, words in enumerate(rows):
        words.sort(key=lambda word: word[0])
        text = _clean_tokens([word[4] for word in words])
        if not text:
            continue
        lines.append(_Line(
            text=text,
            rect=pymupdf.Rect(
                min(word[0] for word in words), min(word[1] for word in words),
                max(word[2] for word in words), max(word[3] for word in words),
            ),
            block_number=index,
            line_number=0,
        ))
    return sorted(lines, key=lambda line: (line.rect.y0, line.rect.x0))


def _is_readable_label(value: str | None) -> bool:
    if not value or not re.search(r"[A-Za-z]", value):
        return False
    return not _INTERNAL_NAME.search(value)


def _vertical_overlap(first: pymupdf.Rect, second: pymupdf.Rect) -> float:
    return max(0.0, min(first.y1, second.y1) - max(first.y0, second.y0))


def _direct_label(rect: pymupdf.Rect, lines: list[_Line]) -> str | None:
    candidates = []
    for index, line in enumerate(lines):
        if not re.search(r"[A-Za-z]", line.text):
            continue
        gap = rect.y0 - line.rect.y1
        if gap < -2 or gap > 18:
            continue
        overlap = max(0.0, min(rect.x1, line.rect.x1) - max(rect.x0, line.rect.x0))
        if overlap <= 0:
            continue
        candidates.append((gap, -overlap, abs(line.rect.x0 - rect.x0), index, line))
    if not candidates:
        return None
    selected = min(candidates)[4]
    related = []
    for line in lines:
        if line.block_number != selected.block_number or abs(line.rect.y0 - selected.rect.y0) > 18:
            continue
        horizontal_overlap = max(
            0.0, min(selected.rect.x1, line.rect.x1) - max(selected.rect.x0, line.rect.x0)
        )
        narrower_width = min(selected.rect.width, line.rect.width)
        if line is selected or abs(line.rect.x0 - selected.rect.x0) <= 8 or (
            narrower_width and horizontal_overlap / narrower_width >= 0.5
        ):
            related.append(line)
    related.sort(key=lambda line: (line.rect.y0, line.rect.x0))
    return " ".join(dict.fromkeys(line.text for line in related))


def _checkbox_label(rect: pymupdf.Rect, logical_lines: list[_Line], visual_lines: list[_Line]) -> str | None:
    to_right = []
    for line in logical_lines:
        if not re.search(r"[A-Za-z]", line.text) or _vertical_overlap(rect, line.rect) <= 0:
            continue
        if line.rect.x0 >= rect.x1 - 2:
            to_right.append((line.rect.x0 - rect.x1, line.text))
    if to_right:
        return min(to_right)[1]

    same_row = [line for line in visual_lines
                if re.search(r"[A-Za-z]", line.text) and _vertical_overlap(rect, line.rect) > 0]
    return min(same_row, key=lambda line: abs(line.rect.x1 - rect.x0)).text if same_row else None


def _nearby_context(rect: pymupdf.Rect, visual_lines: list[_Line], previous_bottom: float) -> str:
    lower = max(previous_bottom - 1, rect.y0 - 48)
    selected = []
    for line in visual_lines:
        if line.rect.y0 < lower or line.rect.y0 > rect.y1:
            continue
        if not re.search(r"[A-Za-z]", line.text):
            continue
        selected.append(line.text)
    # The original page text is evidence for the next stage, so keep it bounded but intact.
    return " ".join(dict.fromkeys(selected))[:1000]


def _answer_type(label: str, widget_type: int, grouped: bool = False) -> str:
    lowered = label.lower()
    if grouped or widget_type in {pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
                                  pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                                  pymupdf.PDF_WIDGET_TYPE_LISTBOX}:
        return "choice"
    if widget_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
        return "checkbox"
    if any(word in lowered for word in ("amount", "income", "deduction", "withholding", "$")):
        return "currency"
    if "date" in lowered or "born" in lowered:
        return "date"
    if "number of" in lowered or re.search(r"\b(?:count|how many)\b", lowered):
        return "number"
    return "text"


def _question_number(text: str) -> str | None:
    line_code = re.search(r"\b(\d+\([a-z]\))", text, re.IGNORECASE)
    if line_code:
        return line_code.group(1)
    leading = re.match(r"^\s*(\d+[a-z]?)(?:[.)]|\s)", text, re.IGNORECASE)
    if leading:
        return leading.group(1)
    step = re.search(r"\bStep\s+(\d+[a-z]?)\b", text, re.IGNORECASE)
    return step.group(1) if step else None


def _step_section_title(text: str) -> str | None:
    step = re.search(r"\bStep\s+(\d+[a-z]?)\b", text, re.IGNORECASE)
    return f"Step {step.group(1)}" if step else None


def _page_section_headings(blocks: list[_TextBlock], cutoff: float) -> list[tuple[float, str]]:
    headings = []
    for block in blocks:
        if block.rect.y0 >= cutoff:
            continue
        match = re.match(r"^(Part\s+[IVXLC]+)\s+(.+)$", block.text, re.IGNORECASE)
        if match:
            headings.append((block.rect.y0, f"{match.group(1)} {match.group(2)}"))
    return headings


def _section_for_y(y: float, headings: list[tuple[float, str]]) -> str | None:
    preceding = [heading for heading_y, heading in headings if heading_y <= y]
    return preceding[-1] if preceding else None


def _group_section_for_y(y: float, groups: list[tuple[float, float, str]]) -> str | None:
    matches = [title for start, end, title in groups if start <= y < end]
    return matches[-1] if matches else None


def _checkbox_group_name(name: str) -> str:
    return re.sub(r"\[\d+\]$", "", name)


def _union(rects: list[pymupdf.Rect]) -> pymupdf.Rect:
    result = pymupdf.Rect(rects[0])
    for rect in rects[1:]:
        result.include_rect(rect)
    return result


def _text_blocks(page: pymupdf.Page) -> list[_TextBlock]:
    blocks = []
    for raw in page.get_text("blocks", sort=True):
        if len(raw) < 7 or raw[6] != 0:
            continue
        text = _clean_tokens(raw[4].split())
        if text:
            blocks.append(_TextBlock(text, pymupdf.Rect(raw[:4]), int(raw[5])))
    return blocks


def _small_boxes(page: pymupdf.Page) -> list[pymupdf.Rect]:
    boxes = []
    for drawing in page.get_drawings():
        rect = pymupdf.Rect(drawing["rect"])
        if 5 <= rect.width <= 20 and 5 <= rect.height <= 30:
            boxes.append(rect)
    return boxes


def _horizontal_rules(page: pymupdf.Page) -> list[pymupdf.Rect]:
    rules = []
    for drawing in page.get_drawings():
        rect = pymupdf.Rect(drawing["rect"])
        if rect.width >= 20 and rect.height <= 1.5:
            rules.append(rect)
    return rules


def _option_for_box(box: pymupdf.Rect, lines: list[_Line]) -> str | None:
    candidates = []
    for line in lines:
        if not re.search(r"[A-Za-z]", line.text):
            continue
        if _vertical_overlap(box, line.rect) <= 0 or line.rect.x0 < box.x1 - 2:
            continue
        candidates.append((line.rect.x0 - box.x1, line))
    if not candidates:
        return None
    gap, line = min(candidates, key=lambda candidate: candidate[0])
    return line.text if gap <= 14 else None


def _instruction_cutoff(page: pymupdf.Page, blocks: list[_TextBlock]) -> float:
    headings = (
        "general instructions", "specific instructions", "instructions for",
        "part ii. certification", "part ii certification",
    )
    matches = [block.rect.y0 for block in blocks
               if any(block.text.lower().startswith(heading) for heading in headings)]
    return min(matches, default=page.rect.height)


def _has_answer_geometry(rect: pymupdf.Rect, rules: list[pymupdf.Rect],
                         boxes: list[pymupdf.Rect]) -> bool:
    center = (rect.x0 + rect.x1) / 2
    if any(rect.y1 - 2 <= rule.y0 <= rect.y1 + 14 and
           rule.x1 >= rect.x1 - 2 and rule.x0 <= rect.x1 + 12 for rule in rules):
        return True
    if any(rect.y1 - 2 <= box.y0 <= rect.y1 + 34 and
           box.x1 >= rect.x0 - 5 and box.x0 <= rect.x1 + 80 for box in boxes):
        return True
    above = [rule for rule in rules if 0 <= rect.y0 - rule.y0 <= 4 and rule.x0 <= center <= rule.x1]
    below = [rule for rule in rules if 0 <= rule.y0 - rect.y1 <= 60 and rule.x0 <= center <= rule.x1]
    return bool(above and below)


def _related_line_text(selected: _Line, lines: list[_Line]) -> str:
    related = []
    for line in lines:
        if line.block_number != selected.block_number or abs(line.rect.y0 - selected.rect.y0) > 18:
            continue
        overlap = max(0.0, min(selected.rect.x1, line.rect.x1) - max(selected.rect.x0, line.rect.x0))
        narrow = min(selected.rect.width, line.rect.width)
        if line is selected or abs(line.rect.x0 - selected.rect.x0) <= 8 or (narrow and overlap / narrow >= 0.5):
            related.append(line)
    related.sort(key=lambda line: (line.rect.y0, line.rect.x0))
    return " ".join(dict.fromkeys(line.text for line in related))


def _extract_text_layer_fields(document: pymupdf.Document) -> list[FormField]:
    """Conservatively extract prompts from a non-fillable PDF text layer."""
    fields = []
    used_ids: dict[tuple[int, str], int] = defaultdict(int)
    for page_number, page in enumerate(document, 1):
        blocks = _text_blocks(page)
        cutoff = _instruction_cutoff(page, blocks)
        candidates = []
        group_blocks = []
        for block in blocks:
            match = _NUMBERED_PROMPT.match(block.text)
            if not match or block.rect.y0 >= cutoff:
                continue
            if match.group(2).strip().endswith(":"):
                group_blocks.append((block, match.group(1), match.group(2).rstrip(":").strip()))
                continue
            candidates.append((block, match.group(1), match.group(2)))

        drawings = page.get_drawings()
        if len(candidates) < 3 or len(drawings) < len(candidates):
            continue

        logical_lines = _logical_lines(page)
        boxes = _small_boxes(page)
        rules = _horizontal_rules(page)
        section_headings = _page_section_headings(blocks, cutoff)
        group_sections = []
        for group_block, identifier, title in group_blocks:
            next_prompt_y = min(
                (block.rect.y0 for block, _, _ in candidates if block.rect.y0 > group_block.rect.y0),
                default=cutoff,
            )
            group_sections.append(
                (group_block.rect.y0, next_prompt_y, f"{identifier} {title}")
            )
        used_option_blocks = set()
        numbered_blocks = {candidate[0].block_number for candidate in candidates}
        first_prompt_y = min(candidate[0].rect.y0 for candidate in candidates)

        for index, (block, identifier, label) in enumerate(candidates):
            later = [other.rect.y0 for other, _, _ in candidates[index + 1:]
                     if other.rect.y0 > block.rect.y0 and
                     max(0.0, min(block.rect.x1, other.rect.x1) - max(block.rect.x0, other.rect.x0)) > 0]
            bottom = min(later, default=cutoff)
            nearby_boxes = [box for box in boxes
                            if block.rect.y0 <= box.y0 < bottom and
                            block.rect.x0 - 5 <= box.x0 <= block.rect.x1 + 20]
            options = []
            for box in nearby_boxes:
                option = _option_for_box(box, logical_lines)
                if option and option not in options:
                    options.append(option)
                    used_option_blocks.update(
                        line.block_number for line in logical_lines if line.text == option
                    )
            answer_type = "choice" if len(options) > 1 else (
                "checkbox" if len(nearby_boxes) == 1 else _answer_type(label, pymupdf.PDF_WIDGET_TYPE_TEXT)
            )
            rects = [block.rect, *nearby_boxes]
            source_rect = _union(rects)
            source_context = block.text
            if options:
                source_context += " Options: " + "; ".join(options)
            key = (page_number, identifier.lower())
            used_ids[key] += 1
            suffix = f"-{used_ids[key]}" if used_ids[key] > 1 else ""
            fields.append(FormField(
                field_id=f"p{page_number}:text:{identifier.lower()}{suffix}",
                question_number=identifier,
                section_title=_section_for_y(block.rect.y0, section_headings),
                original_question=f"{identifier} {label}",
                answer_type=answer_type,
                options=options,
                pdf_field_names=[],
                source_page=page_number,
                source_rect=list(source_rect),
                source_context=source_context[:1000],
                extraction_confidence="medium",
                source_kind="text-layer",
            ))

        # Pick up unnumbered labels attached to blank lines, cells, or digit boxes.
        for line in logical_lines:
            label = line.text.strip()
            words = label.split()
            if (line.rect.y0 < first_prompt_y or line.rect.y0 >= cutoff or
                    line.block_number in numbered_blocks or line.block_number in used_option_blocks):
                continue
            if not (1 <= len(words) <= 12 and len(label) <= 110 and re.search(r"[A-Za-z]", label)):
                continue
            lowered = label.lower()
            excluded_fragments = (
                "instructions", "note:", "part i", "taxpayer identification number",
                "before you begin", "certification", "see specific", "page on",
                "outside the united states",
            )
            if lowered in {"or", "form", "print or type.", "sign here"} or any(
                fragment in lowered for fragment in excluded_fragments
            ):
                continue
            if not _has_answer_geometry(line.rect, rules, boxes):
                continue
            merged = _related_line_text(line, logical_lines)
            if any(fragment in merged.lower() for fragment in excluded_fragments):
                continue
            if any(field.source_page == page_number and field.original_question == merged for field in fields):
                continue
            key_label = re.sub(r"[^a-z0-9]+", "-", merged.lower()).strip("-")[:40] or "field"
            key = (page_number, key_label)
            used_ids[key] += 1
            suffix = f"-{used_ids[key]}" if used_ids[key] > 1 else ""
            fields.append(FormField(
                field_id=f"p{page_number}:text:{key_label}{suffix}",
                question_number=None,
                section_title=(
                    _group_section_for_y(line.rect.y0, group_sections)
                    or _section_for_y(line.rect.y0, section_headings)
                ),
                original_question=merged,
                answer_type=_answer_type(merged, pymupdf.PDF_WIDGET_TYPE_TEXT),
                options=[],
                pdf_field_names=[],
                source_page=page_number,
                source_rect=list(line.rect),
                source_context=merged,
                extraction_confidence="medium",
                source_kind="text-layer",
            ))

    fields.sort(key=lambda field: (field.source_page, field.source_rect[1], field.source_rect[0]))
    return fields


def extract_fields(data: bytes) -> list[FormField]:
    """Extract supported fillable fields and their nearby source text.

    This is deliberately deterministic. The parser gathers evidence for an LLM but
    does not ask an LLM to discover fields or invent labels.
    """
    extracted: list[_ExtractedWidget] = []
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("Please upload an unlocked PDF.")
        for page_number, page in enumerate(document, 1):
            widgets = [widget for widget in (page.widgets() or [])
                       if widget.field_type in _SUPPORTED_TYPES]
            logical_lines = _logical_lines(page)
            visual_lines = _visual_lines(page)
            for widget in widgets:
                previous_bottom = max((other.rect.y1 for other in widgets
                                       if other.rect.y1 <= widget.rect.y0 and other.xref != widget.xref),
                                      default=widget.rect.y0 - 48)
                context = _nearby_context(widget.rect, visual_lines, previous_bottom)
                supplied_label = widget.field_label if _is_readable_label(widget.field_label) else None
                if supplied_label:
                    label = supplied_label
                    confidence = "high"
                elif widget.field_type in {pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                                           pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON}:
                    inferred = _checkbox_label(widget.rect, logical_lines, visual_lines)
                    label = context if widget.rect.x0 > page.rect.width * 0.75 else inferred or context
                    confidence = "medium"
                else:
                    label = _direct_label(widget.rect, logical_lines) or context
                    confidence = "medium"
                if not label:
                    label = widget.field_name or f"Field {widget.xref}"
                extracted.append(_ExtractedWidget(
                    xref=widget.xref,
                    name=widget.field_name or f"field-{widget.xref}",
                    field_type=widget.field_type,
                    label=label,
                    context=context or label,
                    rect=pymupdf.Rect(widget.rect),
                    page_number=page_number,
                    confidence=confidence,
                ))

        if not extracted:
            text_fields = _extract_text_layer_fields(document)
            if text_fields:
                if len(text_fields) > 100:
                    raise ValueError("Please use a form with 100 fields or fewer for this demo.")
                _attach_worksheet_workflows(document, text_fields)
                _attach_eligibility_workflows(document, text_fields)
                _attach_table_lookup_workflows(document, text_fields)
                return text_fields
            from .ocr import extract_ocr_fields
            ocr_fields = extract_ocr_fields(document)
            if ocr_fields:
                _attach_worksheet_workflows(document, ocr_fields)
                _attach_eligibility_workflows(document, ocr_fields)
                _attach_table_lookup_workflows(document, ocr_fields)
                return ocr_fields

    if not extracted:
        raise ValueError(
            "No fillable fields, text-based questions, or recognizable scanned questions were found."
        )

    checkbox_groups: dict[tuple[int, str], list[_ExtractedWidget]] = defaultdict(list)
    ungrouped = []
    for item in extracted:
        if item.field_type in {pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                               pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON}:
            checkbox_groups[(item.page_number, _checkbox_group_name(item.name))].append(item)
        else:
            ungrouped.append(item)

    fields: list[FormField] = []
    for item in ungrouped:
        fields.append(FormField(
            field_id=f"p{item.page_number}:{item.xref}",
            question_number=_question_number(f"{item.label} {item.context}"),
            section_title=_step_section_title(item.context),
            original_question=item.label,
            answer_type=_answer_type(item.label, item.field_type),
            options=[],
            pdf_field_names=[item.name],
            source_page=item.page_number,
            source_rect=list(item.rect),
            source_context=item.context,
            extraction_confidence=item.confidence,
        ))

    for (_, _), items in checkbox_groups.items():
        items.sort(key=lambda item: (item.rect.y0, item.rect.x0))
        grouped = len(items) > 1
        options = [item.label for item in items] if grouped else []
        question = f"Select one: {'; '.join(options)}" if grouped else items[0].label
        rect = _union([item.rect for item in items])
        context = " ".join(dict.fromkeys(item.context for item in items))[:1000]
        fields.append(FormField(
            field_id="p{}:{}".format(items[0].page_number, ",".join(str(item.xref) for item in items)),
            question_number=_question_number(f"{question} {context}"),
            section_title=_step_section_title(context),
            original_question=question,
            answer_type=_answer_type(question, items[0].field_type, grouped=grouped),
            options=options,
            pdf_field_names=[item.name for item in items],
            source_page=items[0].page_number,
            source_rect=list(rect),
            source_context=context,
            extraction_confidence="medium",
        ))

    fields.sort(key=lambda field: (field.source_page, field.source_rect[1], field.source_rect[0]))
    if len(fields) > 100:
        raise ValueError("Please use a form with 100 fields or fewer for this demo.")
    with pymupdf.open(stream=data, filetype="pdf") as document:
        _attach_worksheet_workflows(document, fields)
        _attach_eligibility_workflows(document, fields)
        _attach_table_lookup_workflows(document, fields)
    return fields
