from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .models import WorksheetExpression, WorksheetSpec


def _currency(value: str) -> Decimal:
    try:
        number = Decimal(value.strip().replace("$", "").replace(",", ""))
    except (InvalidOperation, AttributeError):
        raise ValueError("Enter a valid amount for every worksheet question.") from None
    if not number.is_finite() or number < 0:
        raise ValueError("Worksheet amounts must be zero or greater.")
    return number


def calculate_worksheet(spec: WorksheetSpec, answers: dict[str, str]) -> Decimal:
    inputs = {item.input_id: item for item in spec.inputs}
    if set(answers) != set(inputs):
        raise ValueError("Complete every worksheet question before calculating the result.")

    numeric: dict[str, Decimal] = {}
    choices: dict[str, str] = {}
    for input_id, item in inputs.items():
        answer = answers[input_id]
        if item.answer_type == "currency":
            numeric[input_id] = _currency(answer)
        elif answer not in item.options:
            raise ValueError("Choose one of the worksheet options provided.")
        else:
            choices[input_id] = answer

    def evaluate(expression: WorksheetExpression, depth: int = 0) -> Decimal:
        if depth > 30:
            raise ValueError("The worksheet formula is too deeply nested.")
        operation = expression.operation
        values = [evaluate(item, depth + 1) for item in expression.operands]
        if operation == "input":
            if expression.input_id not in numeric or expression.operands:
                raise ValueError("The worksheet formula references an invalid numeric input.")
            return numeric[expression.input_id]
        if operation == "constant":
            if expression.value is None or expression.operands:
                raise ValueError("The worksheet formula contains an invalid constant.")
            return Decimal(str(expression.value))
        if operation == "lookup":
            answer = choices.get(expression.input_id or "")
            if answer is None or answer not in expression.choices or expression.operands:
                raise ValueError("The worksheet formula references an invalid choice.")
            return Decimal(str(expression.choices[answer]))
        if operation == "add" and values:
            return sum(values, Decimal(0))
        if operation == "subtract" and len(values) == 2:
            return values[0] - values[1]
        if operation == "max" and values:
            return max(values)
        if operation == "multiply" and len(values) == 2:
            return values[0] * values[1]
        if operation == "if_greater" and len(values) == 4:
            return values[2] if values[0] > values[1] else values[3]
        raise ValueError("The worksheet contains an unsupported formula.")

    result = evaluate(spec.result_expression)
    if result < 0:
        raise ValueError("The worksheet produced an invalid negative result.")
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
