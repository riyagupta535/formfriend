import pytest

from app.text_utils import strip_form_reference


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("(b) Social security number", "Social security number"),
        ("3a Federal tax classification", "Federal tax classification"),
        ("4(b) Deductions", "Deductions"),
        ("Line 2: Business name", "Business name"),
        ("Step 4(b) · Other income", "Other income"),
        ("2026 tax withholding", "2026 tax withholding"),
        ("How many children are under age 17?", "How many children are under age 17?"),
    ],
)
def test_strip_form_reference(source, expected):
    assert strip_form_reference(source) == expected
