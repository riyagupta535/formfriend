import asyncio
import json
import pymupdf
import pytest
from app.parser import extract_fields
from app.models import TableLookupSpec, WageRange, WageTable, WageTableRow
from app.table_lookups import lookup_wage_table
from app.conversation import simplify, simplify_fields
from app.main import answer, sessions
from app.models import Answer, FormField, Session
from app.ocr import (
    OCRLine, _cutoff, _label_fields, _numbered_fields,
    deduplicate_image_fields, extract_image_fields,
)
import time

def sample():
    document = pymupdf.open()
    page = document.new_page()
    widget = pymupdf.Widget()
    widget.field_name = "Full name"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(40, 70, 300, 100)
    page.add_widget(widget)
    data = document.tobytes()
    document.close()
    return data

def sample_with_unlabeled_controls():
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((40, 60), "Applicant legal name")
    text = pymupdf.Widget()
    text.field_name = "f1_01[0]"
    text.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    text.rect = pymupdf.Rect(40, 70, 300, 100)
    page.add_widget(text)
    for index, option in enumerate(("Single", "Married filing jointly")):
        y = 125 + index * 24
        checkbox = pymupdf.Widget()
        checkbox.field_name = f"filing_status[{index}]"
        checkbox.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
        checkbox.rect = pymupdf.Rect(40, y, 52, y + 12)
        page.add_widget(checkbox)
        page.insert_text((60, y + 10), option)
    data = document.tobytes()
    document.close()
    return data

def sample_nonfillable_form():
    document = pymupdf.open()
    page = document.new_page()
    prompts = (
        (50, "1 Full legal name"),
        (120, "2 Mailing address"),
        (190, "3 Phone number"),
    )
    for y, prompt in prompts:
        page.insert_text((40, y), prompt)
        page.draw_line((40, y + 30), (350, y + 30))
    data = document.tobytes()
    document.close()
    return data

def sample_with_dependent_worksheet():
    document = pymupdf.open()
    first = document.new_page()
    widget = pymupdf.Widget()
    widget.field_name = "Deductions Worksheet on page 4 result"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(40, 70, 300, 100)
    first.add_widget(widget)
    document.new_page()
    document.new_page()
    worksheet = document.new_page()
    worksheet.insert_textbox(
        pymupdf.Rect(30, 30, 580, 500),
        "\n".join([
            "Step 4(b)—Deductions Worksheet",
            "Add lines 1a, 1b, and 1c",
            "Add lines 3a and 3b",
            "Add lines 6a, 6b, 6c, 6d, and 6e",
            "multiply line 7 by 94% (0.94)",
            "Add lines 2, 4, 5, and 14",
            "enter the result here and in Step 4(b)",
            "$768,700 $640,600 $384,350",
            "$32,200 $24,150 $16,100 $6,000",
        ]),
        fontsize=10,
    )
    worksheet_widget = pymupdf.Widget()
    worksheet_widget.field_name = "Worksheet line 15"
    worksheet_widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    worksheet_widget.rect = pymupdf.Rect(400, 600, 550, 625)
    worksheet.add_widget(worksheet_widget)
    data = document.tobytes()
    document.close()
    return data

def sample_with_exemption_workflow():
    document = pymupdf.open()
    first = document.new_page()
    checkbox = pymupdf.Widget()
    checkbox.field_name = "I claim exemption from withholding for 2026. See page 2"
    checkbox.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
    checkbox.rect = pymupdf.Rect(40, 70, 55, 85)
    first.add_widget(checkbox)
    instructions = document.new_page()
    instructions.insert_textbox(
        pymupdf.Rect(30, 30, 580, 500),
        "\n".join([
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
        ]),
        fontsize=10,
    )
    data = document.tobytes()
    document.close()
    return data

def test_pdf_field_locations():
    fields = extract_fields(sample())
    assert len(fields) == 1
    assert fields[0].original_question == "Full name"
    assert fields[0].source_page == 1
    assert len(fields[0].source_rect) == 4

def test_empty_pdf_rejected():
    with pymupdf.open() as doc:
        doc.new_page()
        with pytest.raises(ValueError, match="No questions"):
            extract_fields(doc.tobytes())

def test_unlabeled_text_uses_nearby_page_text():
    fields = extract_fields(sample_with_unlabeled_controls())
    assert fields[0].original_question == "Applicant legal name"
    assert fields[0].source_context == "Applicant legal name"
    assert fields[0].pdf_field_names == ["f1_01[0]"]

def test_related_checkboxes_are_grouped_as_one_choice():
    fields = extract_fields(sample_with_unlabeled_controls())
    choice = fields[1]
    assert choice.answer_type == "choice"
    assert choice.options == ["Single", "Married filing jointly"]
    assert len(choice.pdf_field_names) == 2

def test_nonfillable_text_form_extracts_numbered_prompts():
    fields = extract_fields(sample_nonfillable_form())
    assert [field.original_question for field in fields] == [
        "1 Full legal name", "2 Mailing address", "3 Phone number"
    ]
    assert all(field.source_kind == "text-layer" for field in fields)
    assert all(field.pdf_field_names == [] for field in fields)
    assert [field.question_number for field in fields] == ["1", "2", "3"]
    assert all(field.section_title is None for field in fields)

def test_parser_attaches_referenced_worksheet_as_a_subtask():
    fields = extract_fields(sample_with_dependent_worksheet())
    assert len(fields) == 1
    field = fields[0]
    assert field.worksheet is not None
    assert field.worksheet.source_page == 4
    assert field.worksheet.result_line == "15"
    assert len(field.worksheet.inputs) == 14
    assert all(item.source_page != 4 for item in fields)

def test_backend_calculates_w4_worksheet_from_extracted_formula():
    from app.worksheets import calculate_worksheet
    field = extract_fields(sample_with_dependent_worksheet())[0]
    answers = {
        item.input_id: (
            "Single" if item.input_id == "filing_status"
            else "No" if item.answer_type == "choice"
            else "0"
        )
        for item in field.worksheet.inputs
    }
    answers.update({
        "1a": "1000", "1b": "2000", "1c": "3000", "3a": "Yes",
        "5": "400", "6a": "10000", "8a": "100000", "12": "500",
    })
    assert calculate_worksheet(field.worksheet, answers) == 12900

    answers.pop("12")
    with pytest.raises(ValueError, match="Complete every worksheet"):
        calculate_worksheet(field.worksheet, answers)

def test_parser_attaches_exemption_eligibility_conditions():
    field = extract_fields(sample_with_exemption_workflow())[0]
    workflow = field.eligibility_workflow
    assert workflow is not None
    assert workflow.source_page == 2
    assert workflow.checked_value not in {"", "Off"}
    assert [item.condition_id for item in workflow.conditions] == [
        "no_2025_liability", "expect_no_2026_liability"
    ]
    assert "total tax" in workflow.conditions[0].unsure_help
    assert "line 24" not in workflow.conditions[0].unsure_help
    assert "no federal income tax" in workflow.eligible_explanation

def test_wage_table_lookup_uses_filing_status_and_both_wages():
    lookup = TableLookupSpec(
        lookup_id="test",
        source_page=5,
        intro_question="Find the amount.",
        intro_helper_text="Answer the questions.",
        higher_wage_label="Higher wages?",
        lower_wage_label="Lower wages?",
        tables=[WageTable(
            filing_status="Single",
            columns=[WageRange(minimum=0, maximum=9999), WageRange(minimum=10000, maximum=19999)],
            rows=[
                WageTableRow(minimum=0, maximum=49999, values=[100, 200]),
                WageTableRow(minimum=50000, maximum=None, values=[300, 400]),
            ],
        )],
    )
    assert lookup_wage_table(lookup, "Single", 75000, 15000) == 400
    # Reversed user inputs are normalized to higher- and lower-paying wages.
    assert lookup_wage_table(lookup, "Single", 15000, 75000) == 400
    with pytest.raises(ValueError, match="outside this table"):
        lookup_wage_table(lookup, "Single", 75000, 25000)

def test_ocr_lines_keep_question_identity_and_confidence():
    lines = [
        OCRLine("1Name of applicant", pymupdf.Rect(40, 50, 220, 65), .98),
        OCRLine("2", pymupdf.Rect(40, 100, 48, 115), .96),
        OCRLine("Mailing address", pymupdf.Rect(60, 100, 220, 115), .97),
        OCRLine("3bEligibility confirmation", pymupdf.Rect(40, 150, 250, 165), .91),
        OCRLine("Certification", pymupdf.Rect(40, 210, 150, 225), .99),
        OCRLine("1.Not a form question", pymupdf.Rect(40, 240, 250, 255), .99),
    ]
    cutoff = _cutoff(lines, 792)
    fields = _numbered_fields(lines, 1, 612, cutoff)
    assert [field.question_number for field in fields] == ["1", "2", "3b"]
    assert fields[0].original_question == "1 Name of applicant"
    assert fields[1].original_question == "2 Mailing address"
    assert all(field.source_kind == "ocr" for field in fields)
    assert all(field.ocr_confidence is not None for field in fields)

def test_ocr_recognizes_common_unnumbered_w9_labels():
    line = OCRLine("Socialsecuritynumber", pymupdf.Rect(400, 300, 520, 315), .99)
    fields = _label_fields([line], 1, 792, [])
    assert fields[0].original_question == "Social security number"
    assert fields[0].source_context == "Socialsecuritynumber"

def test_screenshot_ocr_extracts_labels_choices_and_numbered_lines(monkeypatch):
    lines = [
        OCRLine("Your first name and middle initial", pymupdf.Rect(40, 40, 250, 55), .98),
        OCRLine("Last name", pymupdf.Rect(300, 40, 380, 55), .97),
        OCRLine("Filing Status", pymupdf.Rect(40, 80, 140, 95), .99),
        OCRLine("Single", pymupdf.Rect(160, 80, 220, 95), .99),
        OCRLine("Head of household (HOH)", pymupdf.Rect(250, 80, 450, 95), .98),
        OCRLine("1a", pymupdf.Rect(40, 130, 65, 145), .99),
        OCRLine("Total wages", pymupdf.Rect(75, 130, 180, 145), .96),
    ]
    monkeypatch.setattr('app.ocr._ocr_image', lambda _: (lines, 600, 800))
    fields = extract_image_fields(b'ignored')
    assert next(field for field in fields if field.field_id == 'image:ocr:your-name').ocr_confidence == .98
    filing = next(field for field in fields if field.field_id == 'image:ocr:filing-status')
    assert filing.answer_type == 'choice'
    assert filing.options == ['Single', 'Head of household']
    income = next(field for field in fields if field.question_number == '1a')
    assert income.field_id == 'image:ocr:line-1a'
    assert income.original_question == '1a Total wages'

def test_overlapping_screenshot_questions_are_deduplicated():
    first = FormField(
        field_id='first', question_number='1a', original_question='1a Total wages from Forms W-2',
        source_page=1, source_rect=[10, 10, 200, 20], source_kind='ocr', ocr_confidence=.91,
    )
    clearer_overlap = FormField(
        field_id='second', question_number='1a', original_question='1a Totalwages from Forms W-2',
        source_page=1, source_rect=[10, 300, 200, 310], source_kind='ocr', ocr_confidence=.98,
    )
    different_line = FormField(
        field_id='third', question_number='1b', original_question='1b Total wages from Forms W-2',
        source_page=1, source_rect=[10, 330, 200, 340], source_kind='ocr', ocr_confidence=.99,
    )
    fields, removed = deduplicate_image_fields([[first], [clearer_overlap, different_line]])
    assert removed == 1
    assert len(fields) == 2
    assert fields[0].ocr_confidence == .98
    assert fields[0].source_page == 2
    assert fields[0].field_id == 'image:ocr:1a'
    assert fields[1].field_id == 'image:ocr:1b'

def test_mock_is_explicit(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert asyncio.run(simplify("Full name")) == "Please tell me: Full name"

def test_gemini_batches_context_and_applies_structured_results(monkeypatch):
    import httpx
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_BASE_URL", "https://gemini.example/v1beta")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    fields = [
        FormField(
            field_id="name", original_question="Legal name", section_title="Identity",
            source_context="Enter the name shown on your official records.",
            source_page=1, source_rect=[],
        ),
        FormField(
            field_id="status", original_question="Tax classification", answer_type="choice",
            options=["Individual", "Partnership"], source_page=1, source_rect=[],
        ),
    ]
    captured = {"payloads": []}

    async def fake_post(self, url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs["headers"]
        captured["payloads"].append(kwargs["json"])
        request_text = kwargs["json"]["contents"][0]["parts"][0]["text"]
        request_data = json.loads(request_text.split("\n\n", 1)[0])
        requested_ids = {item["field_id"] for item in request_data["fields"]}
        results = [{
                "field_id": "name", "plain_question": "What is your legal name?",
                "helper_text": "Use the name on your official records.",
                "subquestions": [], "decision_tree": None, "confidence": "high",
            },
            {
                "field_id": "status", "plain_question": "What is your tax classification?",
                "helper_text": None,
                "subquestions": [{
                    "text": "Which classification applies?", "answer_type": "choice",
                    "options": ["Individual", "Partnership"],
                }],
                "decision_tree": None,
                "confidence": "medium",
            },
        ]
        content = json.dumps({
            "results": [item for item in results if item["field_id"] in requested_ids]
        })
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": content}]},
        }]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    warnings = asyncio.run(simplify_fields(fields))

    assert warnings == []
    assert captured["url"] == (
        "https://gemini.example/v1beta/models/gemini-3.5-flash-lite:generateContent"
    )
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert len(captured["payloads"]) == 2
    assert all(
        payload["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "minimal"
        for payload in captured["payloads"]
    )
    assert all(
        payload["generationConfig"]["responseMimeType"] == "application/json"
        for payload in captured["payloads"]
    )
    request_fields = [
        item
        for payload in captured["payloads"]
        for item in json.loads(
            payload["contents"][0]["parts"][0]["text"].split("\n\n", 1)[0]
        )["fields"]
    ]
    name_request = next(item for item in request_fields if item["field_id"] == "name")
    assert name_request["section_title"] == "Identity"
    assert name_request["source_context"].startswith("Enter the name")
    assert fields[0].simplified_question == "What is your legal name?"
    assert fields[0].helper_text == "Use the name on your official records."
    assert fields[0].simplification_status == "complete"
    assert fields[1].subquestions[0].options == ["Individual", "Partnership"]
    assert fields[1].simplification_confidence == "medium"

def test_gemini_reuses_valid_cached_response_without_an_api_call(monkeypatch, tmp_path):
    import httpx
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_BASE_URL", "https://gemini.example/v1beta")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    monkeypatch.setenv("GEMINI_CACHE_TTL_SECONDS", "3600")
    monkeypatch.setenv("GEMINI_CACHE_PATH", str(tmp_path / "gemini.sqlite3"))
    calls = 0

    async def fake_post(self, url, **kwargs):
        nonlocal calls
        calls += 1
        content = json.dumps({"results": [{
            "field_id": "name",
            "plain_question": "What is your legal name?",
            "helper_text": "Use the name on your official records.",
            "subquestions": [],
            "calculation": None,
            "decision_tree": None,
            "confidence": "high",
        }]})
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": content}]},
        }]}, request=httpx.Request("POST", url))

    def field():
        return FormField(
            field_id="name", original_question="Legal name", section_title="Identity",
            source_context="Enter the name shown on your official records.",
            source_page=1, source_rect=[], simplification_status="pending",
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    first = field()
    second = field()
    assert asyncio.run(simplify_fields([first])) == []
    assert asyncio.run(simplify_fields([second])) == []

    assert calls == 1
    assert second.simplified_question == "What is your legal name?"
    assert second.simplification_status == "complete"
    assert (tmp_path / "gemini.sqlite3").exists()

def test_decision_tree_covers_exact_original_options():
    from app.conversation import _validate_batch
    from app.models import SimplificationBatch
    field = FormField(
        field_id="filing", original_question="Select one", answer_type="choice",
        options=["Single", "Married filing jointly", "Head of household"],
        source_page=1, source_rect=[],
    )
    payload = {
        "results": [{
            "field_id": "filing", "plain_question": "Let’s determine your filing status.",
            "helper_text": None, "subquestions": [], "confidence": "high",
            "decision_tree": {
                "start_node_id": "married",
                "nodes": [
                    {
                        "node_id": "married", "question": "Are you married?", "helper_text": None,
                        "answers": [
                            {"label": "Yes", "next_node_id": None, "terminal_option": "Married filing jointly"},
                            {"label": "No", "next_node_id": "household", "terminal_option": None},
                        ],
                    },
                    {
                        "node_id": "household", "question": "Do you qualify as head of household?",
                        "helper_text": "Check the eligibility rules shown on the form.",
                        "answers": [
                            {"label": "Yes", "next_node_id": None, "terminal_option": "Head of household"},
                            {"label": "No", "next_node_id": None, "terminal_option": "Single"},
                        ],
                    },
                ],
            },
        }]
    }
    batch = SimplificationBatch.model_validate(payload)
    _validate_batch(batch, [field])

    payload["results"][0]["decision_tree"]["nodes"][1]["answers"][1]["terminal_option"] = "Other"
    invalid = SimplificationBatch.model_validate(payload)
    with pytest.raises(ValueError, match="changed an original option"):
        _validate_batch(invalid, [field])

def test_checkbox_is_sent_and_validated_as_an_implicit_yes_no_choice():
    from app.conversation import _request_fields, _validate_batch
    from app.models import SimplificationBatch
    field = FormField(
        field_id="multiple-jobs", original_question="Check this box if there are two jobs",
        answer_type="checkbox", options=[], source_page=1, source_rect=[],
    )
    assert _request_fields([field])[0]["options"] == ["Yes", "No"]

    batch = SimplificationBatch.model_validate({"results": [{
        "field_id": "multiple-jobs",
        "plain_question": "Are there exactly two jobs in your household?",
        "helper_text": None,
        "subquestions": [],
        "calculation": None,
        "decision_tree": {
            "start_node_id": "two-jobs",
            "nodes": [{
                "node_id": "two-jobs",
                "question": "Are there exactly two jobs in your household?",
                "helper_text": None,
                "answers": [
                    {"label": "Yes", "next_node_id": None, "terminal_option": "Yes"},
                    {"label": "No", "next_node_id": None, "terminal_option": "No"},
                ],
            }],
        },
        "confidence": "high",
    }]})

    _validate_batch(batch, [field])

def test_llm_child_credit_calculation_is_validated_and_applied():
    from app.conversation import _apply_response, _validate_batch
    from app.models import SimplificationBatch
    field = FormField(
        field_id="step-3a",
        original_question=(
            "If your total income will be $200,000 or less ($400,000 or less "
            "if married filing jointly), multiply the number of qualifying "
            "children under age 17 by $2,200."
        ),
        answer_type="currency",
        source_page=1,
        source_rect=[],
    )
    response = SimplificationBatch.model_validate({"results": [{
        "field_id": "step-3a",
        "plain_question": "What is the total credit amount?",
        "helper_text": None,
        "subquestions": [
            {
                "text": "Is your income $200,000 or less, or $400,000 or less if married filing jointly?",
                "answer_type": "choice",
                "options": ["Yes", "No"],
            },
            {
                "text": "How many qualifying children under age 17 do you have?",
                "answer_type": "number",
                "options": [],
            },
        ],
        "calculation": {
            "operation": "multiply",
            "input_question_indices": [1],
            "factor": 2200,
            "source_question_numbers": [],
            "source_field_ids": [],
            "condition_question_index": 0,
            "condition_answer": "Yes",
            "condition_failure_message": "Check the W-4 instructions for Step 3.",
        },
        "decision_tree": None,
        "confidence": "high",
    }]})

    _validate_batch(response, [field])
    assert _apply_response([field], response) == 0
    assert field.calculation is not None
    assert field.calculation.factor == 2200
    assert field.calculation.input_question_indices == [1]
    assert [item.answer_type for item in field.subquestions] == ["choice", "number"]
    assert "$400,000" in field.subquestions[0].text

def test_llm_other_dependent_calculation_is_validated_and_applied():
    from app.conversation import _apply_response, _validate_batch
    from app.models import SimplificationBatch
    field = FormField(
        field_id="step-3b",
        original_question="Multiply the number of other dependents by $500.",
        answer_type="currency",
        source_page=1,
        source_rect=[],
    )
    response = SimplificationBatch.model_validate({"results": [{
        "field_id": "step-3b",
        "plain_question": "What is the total credit amount for other dependents?",
        "helper_text": None,
        "subquestions": [{
            "text": "How many qualifying other dependents do you have?",
            "answer_type": "number",
            "options": [],
        }],
        "calculation": {
            "operation": "multiply",
            "input_question_indices": [0],
            "factor": 500,
            "source_question_numbers": [],
            "source_field_ids": [],
            "condition_question_index": None,
            "condition_answer": None,
            "condition_failure_message": None,
        },
        "decision_tree": None,
        "confidence": "high",
    }]})

    _validate_batch(response, [field])
    assert _apply_response([field], response) == 0
    assert field.calculation is not None
    assert field.calculation.factor == 500
    assert field.calculation.input_question_indices == [0]
    assert field.calculation.condition_question_index is None
    assert len(field.subquestions) == 1
    assert field.subquestions[0].answer_type == "number"

    response.results[0].calculation.factor = 750
    with pytest.raises(ValueError, match="factor was not found"):
        _validate_batch(response, [field])

def test_llm_addition_reuses_prior_field_answers():
    from app.conversation import _apply_response, _validate_batch
    from app.models import SimplificationBatch
    child_credit = FormField(
        field_id="children", question_number="3(a)", original_question="Child credit",
        answer_type="currency", source_page=1, source_rect=[],
    )
    other_dependent_credit = FormField(
        field_id="dependents", question_number="3(b)", original_question="Other dependent credit",
        answer_type="currency", source_page=1, source_rect=[],
    )
    total = FormField(
        field_id="total", original_question=(
            "Add the amounts from Steps 3(a) and 3(b), plus the amount for other credits."
        ), answer_type="currency", source_page=1, source_rect=[],
    )
    response = SimplificationBatch.model_validate({"results": [{
        "field_id": "total",
        "plain_question": "Let’s calculate your total Step 3 credits.",
        "helper_text": "We’ll reuse your answers from lines 3(a) and 3(b).",
        "subquestions": [
            {
                "text": "Do you expect to claim tax credits besides credits for children or dependents?",
                "helper_text": (
                    "A tax credit is an amount that can lower the tax you owe. "
                    "Do not include child or dependent credits already entered."
                ),
                "answer_type": "choice",
                "options": ["Yes", "No", "I'm not sure"],
            },
            {
                "text": "What is the total amount of those other tax credits?",
                "helper_text": "Enter the total from your tax records or tax-preparation estimate.",
                "answer_type": "currency",
                "options": [],
            },
        ],
        "calculation": {
            "operation": "add",
            "input_question_indices": [1],
            "factor": None,
            "source_question_numbers": ["3(a)", "3(b)"],
            "source_field_ids": [],
            "condition_question_index": 0,
            "condition_answer": "Yes",
            "condition_zero_answers": ["No"],
            "condition_skip_answers": ["I'm not sure"],
            "condition_failure_message": "Leave this blank and review it when you have your tax records.",
        },
        "decision_tree": None,
        "confidence": "high",
    }]})

    _validate_batch(response, [total])
    assert _apply_response([total], response, [child_credit, other_dependent_credit, total]) == 0
    assert total.calculation is not None
    assert total.calculation.source_field_ids == ["children", "dependents"]
    assert total.calculation.condition_zero_answers == ["No"]
    assert total.calculation.condition_skip_answers == ["I'm not sure"]
    assert total.subquestions[0].helper_text.startswith("A tax credit is an amount")

def test_gemini_increases_token_budget_after_length_finish(monkeypatch):
    import httpx
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    field = FormField(
        field_id="classification", original_question="Federal tax classification",
        source_page=1, source_rect=[], simplification_status="pending",
    )
    budgets = []

    async def fake_post(self, url, **kwargs):
        budgets.append(kwargs["json"]["generationConfig"]["maxOutputTokens"])
        if len(budgets) == 1:
            payload = {"candidates": [{
                "finishReason": "MAX_TOKENS",
                "content": {"parts": []},
            }]}
        else:
            content = json.dumps({"results": [{
                "field_id": "classification",
                "plain_question": "What is your federal tax classification?",
                "helper_text": None,
                "subquestions": [],
                "decision_tree": None,
                "confidence": "high",
            }]})
            payload = {"candidates": [{
                "finishReason": "STOP",
                "content": {"parts": [{"text": content}]},
            }]}
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    async def no_wait(delay):
        pass

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr("app.conversation.asyncio.sleep", no_wait)
    warnings = asyncio.run(simplify_fields([field]))

    assert warnings == []
    assert budgets == [4096, 8192]
    assert field.simplification_status == "complete"
    assert field.simplified_question == "What is your federal tax classification?"

def test_gemini_failure_falls_back_without_rejecting_upload(monkeypatch, caplog):
    import httpx
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    field = FormField(
        field_id="name", original_question="Full legal name", source_page=1, source_rect=[]
    )
    attempts = 0
    delays = []

    async def failing_post(self, url, **kwargs):
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("offline", request=httpx.Request("POST", url))

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(httpx.AsyncClient, "post", failing_post)
    monkeypatch.setattr("app.conversation.asyncio.sleep", fake_sleep)
    warnings = asyncio.run(simplify_fields([field]))

    assert attempts == 3
    assert delays == [2.0, 4.0]
    assert field.simplified_question == "Full legal name"
    assert field.simplification_status == "failed"
    assert field.simplification_confidence == "low"
    assert warnings == ["Gemini could not simplify 1 question."]
    assert "error_type=ConnectError" in caplog.text
    assert "field_ids=['name']" in caplog.text

def test_gemini_rate_limit_stays_pending_and_retries_until_success(monkeypatch, caplog):
    import httpx
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    field = FormField(
        field_id="address", original_question="Address", source_page=1, source_rect=[],
        simplification_status="pending",
    )
    attempts = 0
    delays = []

    async def rate_limited_then_success(self, url, **kwargs):
        nonlocal attempts
        attempts += 1
        assert field.simplification_status == "pending"
        request = httpx.Request("POST", url)
        if attempts < 3:
            return httpx.Response(
                429,
                json={"error": {"message": "Too many requests"}},
                request=request,
            )
        content = json.dumps({"results": [{
            "field_id": "address",
            "plain_question": "What is your home address?",
            "helper_text": None,
            "subquestions": [],
            "calculation": None,
            "decision_tree": None,
            "confidence": "high",
        }]})
        return httpx.Response(200, json={"candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": content}]},
        }]}, request=request)

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(httpx.AsyncClient, "post", rate_limited_then_success)
    monkeypatch.setattr("app.conversation.asyncio.sleep", fake_sleep)
    warnings = asyncio.run(simplify_fields([field]))

    assert attempts == 3
    assert delays == [30.0, 60.0]
    assert warnings == []
    assert field.simplification_status == "complete"
    assert field.simplified_question == "What is your home address?"
    assert "keeping questions pending and retrying" in caplog.text

def test_first_question_finishes_before_background_requests_start(monkeypatch):
    from app.models import SimplificationBatch
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fields = [
        FormField(
            field_id=f"field-{index}", original_question=f"Question {index}",
            source_page=1, source_rect=[], simplification_status="pending",
        )
        for index in range(4)
    ]
    started = []

    async def fake_run_batch(client, requested, semaphore):
        field = requested[0]
        started.append(field.field_id)
        if field is not fields[0]:
            assert fields[0].simplification_status == "complete"
        response = SimplificationBatch.model_validate({"results": [{
            "field_id": field.field_id,
            "plain_question": f"Simplified {field.original_question}?",
            "helper_text": None,
            "subquestions": [],
            "calculation": None,
            "decision_tree": None,
            "confidence": "high",
        }]})
        return [(requested, response)]

    monkeypatch.setattr("app.conversation._run_batch", fake_run_batch)
    warnings = asyncio.run(simplify_fields(fields))

    assert warnings == []
    assert started[0] == "field-0"
    assert {field.field_id for field in fields[1:]} == set(started[1:])
    assert all(field.simplification_status == "complete" for field in fields)

def test_failed_batch_is_retried_as_individual_questions(monkeypatch):
    from app.conversation import _run_batch
    from app.models import SimplificationBatch
    fields = [
        FormField(
            field_id=f"field-{index}", original_question=f"Question {index}",
            source_page=1, source_rect=[], simplification_status="pending",
        )
        for index in range(3)
    ]
    calls = []

    async def fake_request(client, requested, semaphore):
        calls.append([field.field_id for field in requested])
        if len(requested) > 1:
            return None
        field = requested[0]
        return SimplificationBatch.model_validate({"results": [{
            "field_id": field.field_id,
            "plain_question": f"Simplified {field.original_question}?",
            "helper_text": None,
            "subquestions": [],
            "decision_tree": None,
            "confidence": "high",
        }]})

    monkeypatch.setattr("app.conversation._request_with_retry", fake_request)
    groups = asyncio.run(_run_batch(None, fields, asyncio.Semaphore(3)))

    assert calls[0] == ["field-0", "field-1", "field-2"]
    assert calls[1:] == [["field-0"], ["field-1"], ["field-2"]]
    assert len(groups) == 3
    assert all(response is not None for _, response in groups)

def test_configured_upload_returns_pending_before_gemini_finishes(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    started = []
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("app.main.start_simplification", lambda key: started.append(key))

    with TestClient(app) as client:
        uploaded = client.post('/sessions', files={'file': ('form.pdf', sample())})
        assert uploaded.status_code == 200
        session = uploaded.json()
        assert session['simplification_status'] == 'pending'
        assert session['fields'][0]['simplification_status'] == 'pending'
        assert session['fields'][0]['simplified_question'] == 'Full name'
        assert started == [session['session_id']]
        client.delete(f"/sessions/{session['session_id']}")

def test_background_simplification_updates_session(monkeypatch):
    from app.main import complete_simplification
    field = FormField(
        field_id="name", original_question="Full legal name", simplified_question="Full legal name",
        source_page=1, source_rect=[],
    )
    session = Session(
        session_id="background", filename="form.pdf", mode="gemini",
        simplification_status="pending", fields=[field],
    )
    sessions[session.session_id] = (time.monotonic(), session)

    async def fake_simplify(fields):
        fields[0].simplified_question = "What is your full legal name?"
        fields[0].simplification_confidence = "high"
        return []

    monkeypatch.setattr("app.main.simplify_fields", fake_simplify)
    asyncio.run(complete_simplification(session.session_id))

    assert session.simplification_status == "complete"
    assert session.fields[0].simplified_question == "What is your full legal name?"
    sessions.pop(session.session_id)

def test_answer_mapping():
    fields = extract_fields(sample())
    sessions["test"] = (time.monotonic(), Session(session_id="test", filename="demo.pdf", mode="mock", fields=fields))
    result = answer("test", fields[0].field_id, Answer(value="Alex Example", confirmed=True))
    assert result.fields[0].interpreted_value == "Alex Example"
    assert result.fields[0].confirmed
    sessions.pop("test")

def test_choice_answer_must_match_an_original_option():
    from fastapi import HTTPException
    field = FormField(
        field_id="filing", original_question="Filing status", answer_type="choice",
        options=["Single", "Married filing jointly"], source_page=1, source_rect=[],
    )
    sessions["choice"] = (
        time.monotonic(),
        Session(session_id="choice", filename="demo.pdf", mode="mock", fields=[field]),
    )
    with pytest.raises(HTTPException) as error:
        answer("choice", "filing", Answer(value="Married", confirmed=True))
    assert error.value.status_code == 422
    result = answer("choice", "filing", Answer(value="Married filing jointly", confirmed=True))
    assert result.fields[0].user_response == "Married filing jointly"
    sessions.pop("choice")

def test_upload_answer_clear(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with TestClient(app) as client:
        uploaded = client.post('/sessions', files={'file': ('demo.pdf', sample(), 'application/pdf')})
        assert uploaded.status_code == 200
        session = uploaded.json()
        assert session['mode'] == 'mock'
        key = session['session_id']
        field_id = session['fields'][0]['field_id']
        saved = client.post(f'/sessions/{key}/fields/{field_id}', json={'value': 'Alex Example', 'confirmed': True})
        assert saved.json()['fields'][0]['confirmed']
        assert client.delete(f'/sessions/{key}').status_code == 200
        assert client.post(f'/sessions/{key}/fields/{field_id}', json={'value': 'x'}).status_code == 404
        assert client.post('/sessions', files={'file': ('bad.pdf', b'not a pdf')}).status_code == 415

def test_pdf_export(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with TestClient(app) as client:
        session = client.post('/sessions', files={'file': ('form.pdf', sample())}).json()
        key = session['session_id']
        field_id = session['fields'][0]['field_id']
        client.post(f'/sessions/{key}/fields/{field_id}', json={'value': 'Sam Sample', 'confirmed': True})
        exported = client.get(f'/sessions/{key}/export')
        assert exported.status_code == 200
        with pymupdf.open(stream=exported.content, filetype='pdf') as document:
            assert next(document[0].widgets()).field_value == 'Sam Sample'
        assert client.get(f'/sessions/{key}').json()['filename'] == 'form.pdf'
        client.delete(f'/sessions/{key}')
        assert client.get(f'/sessions/{key}/export').status_code == 404


def test_nonfillable_pdf_exports_answer_sheet(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with TestClient(app) as client:
        session = client.post(
            '/sessions', files={'file': ('regular.pdf', sample_nonfillable_form())}
        ).json()
        key = session['session_id']
        field_id = session['fields'][0]['field_id']
        client.post(
            f'/sessions/{key}/fields/{field_id}',
            json={'value': 'Alex Example', 'confirmed': True},
        )
        exported = client.get(f'/sessions/{key}/export')
        assert exported.status_code == 200
        assert exported.headers['content-type'].startswith('application/pdf')
        with pymupdf.open(stream=exported.content, filetype='pdf') as document:
            assert len(document) > 1
            assert 'Alex Example' in ''.join(page.get_text() for page in document)
        assert 'formfriend-regular.pdf' in exported.headers['content-disposition']


def test_docx_export(monkeypatch):
    from io import BytesIO
    import zipfile
    from fastapi.testclient import TestClient
    from app.main import app
    from app.documents import paragraphs, W
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    data = BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Full name:</w:t></w:r></w:p></w:body></w:document>')
        archive.writestr('unchanged.txt', 'preserved')
    with TestClient(app) as client:
        uploaded = client.post('/sessions', files={'file': ('form.docx', data.getvalue())})
        assert uploaded.status_code == 200
        session = uploaded.json()
        key = session['session_id']
        assert session['document_type'] == 'docx'
        field_id = session['fields'][0]['field_id']
        client.post(f'/sessions/{key}/fields/{field_id}', json={'value': 'Alex & Sam'})
        exported = client.get(f'/sessions/{key}/export')
        _, items = paragraphs(exported.content)
        assert ''.join(t.text or '' for t in items[0].iter(W + 't')) == 'Full name: Alex & Sam'
        with zipfile.ZipFile(BytesIO(exported.content)) as archive:
            assert archive.read('unchanged.txt') == b'preserved'
        client.delete(f'/sessions/{key}')


def test_invalid_screenshot_rejected():
    from app.documents import extract_image
    with pytest.raises(ValueError, match='could not be read'):
        extract_image(b'image')


def test_screenshot_export(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import FormField
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setattr('app.documents.extract_image_fields', lambda _: [
        FormField(field_id='image:ocr:full-name', original_question='Full name',
                  source_page=1, source_rect=[10, 10, 100, 20], source_kind='ocr',
                  ocr_confidence=.98),
        FormField(field_id='image:ocr:address', original_question='What is your address?',
                  source_page=1, source_rect=[10, 30, 150, 40], source_kind='ocr',
                  ocr_confidence=.97),
    ])
    with pymupdf.open() as document:
        image = document.new_page(width=300, height=300).get_pixmap().tobytes('png')
    with TestClient(app) as client:
        uploaded = client.post('/sessions', files={'file': ('screenshot.png', image)})
        assert uploaded.status_code == 200
        session = uploaded.json()
        assert session['document_type'] == 'image'
        assert len(session['fields']) == 2
        key = session['session_id']
        client.post(f'/sessions/{key}/fields/image:ocr:full-name', json={'value': 'Sam'})
        exported = client.get(f'/sessions/{key}/export')
        assert 'Full name\nSam' in exported.text
        assert '[No answer provided]' in exported.text
        client.delete(f'/sessions/{key}')


def test_multiple_screenshot_upload(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import FormField
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    fields = [FormField(
        field_id='image:ocr:name', original_question='Full name', source_page=1,
        source_rect=[10, 10, 100, 20], source_kind='ocr', ocr_confidence=.98,
    )]
    monkeypatch.setattr('app.main.extract_images', lambda _: (fields, 3))
    with TestClient(app) as client:
        uploaded = client.post('/sessions', files=[
            ('files', ('top.png', b'first', 'image/png')),
            ('files', ('bottom.png', b'second', 'image/png')),
        ])
        assert uploaded.status_code == 200
        session = uploaded.json()
        assert session['filename'] == 'top.png + 1 screenshot'
        assert len(session['fields']) == 1
        assert any('removed 3 overlapping questions' in warning for warning in session['warnings'])


def test_pdf_source_preview_and_unconfigured_speech(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    with TestClient(app) as client:
        session = client.post('/sessions', files={'file': ('form.pdf', sample())}).json()
        key, field_id = session['session_id'], session['fields'][0]['field_id']
        preview = client.get(f'/sessions/{key}/fields/{field_id}/source')
        assert preview.status_code == 200
        assert preview.content.startswith(b'\x89PNG')
        assert client.get(f'/sessions/{key}/fields/{field_id}/speech').status_code == 503
        assert client.get(f'/sessions/{key}/fields/missing/source').status_code == 404
        client.delete(f'/sessions/{key}')


def test_elevenlabs_request(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'test-key')
    monkeypatch.setenv('ELEVENLABS_VOICE_ID', 'test-voice')
    async def fake_post(self, url, **kwargs):
        assert url.endswith('/text-to-speech/test-voice')
        assert kwargs['headers']['xi-api-key'] == 'test-key'
        assert kwargs['json']['text'] == 'Please tell me: Full name'
        return httpx.Response(200, content=b'mock-audio', request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx.AsyncClient, 'post', fake_post)
    with TestClient(app) as client:
        session = client.post('/sessions', files={'file': ('form.pdf', sample())}).json()
        key, field_id = session['session_id'], session['fields'][0]['field_id']
        response = client.get(f'/sessions/{key}/fields/{field_id}/speech')
        assert response.status_code == 200
        assert response.headers['content-type'] == 'audio/mpeg'
        assert response.content == b'mock-audio'
        client.delete(f'/sessions/{key}')
