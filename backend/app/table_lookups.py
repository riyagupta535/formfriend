from .models import TableLookupSpec


def lookup_wage_table(
    spec: TableLookupSpec,
    filing_status: str,
    higher_wage: float,
    lower_wage: float,
) -> int:
    table = next(
        (item for item in spec.tables if item.filing_status == filing_status),
        None,
    )
    if table is None:
        raise ValueError("Choose one of the available filing statuses.")

    high = max(higher_wage, lower_wage)
    low = min(higher_wage, lower_wage)
    column_index = next(
        (
            index for index, column in enumerate(table.columns)
            if low >= column.minimum
            and (column.maximum is None or low <= column.maximum)
        ),
        None,
    )
    if column_index is None:
        raise ValueError(
            "The lower-paying job is outside this table. Use the IRS withholding estimator instead."
        )
    row = next(
        (
            item for item in table.rows
            if high >= item.minimum
            and (item.maximum is None or high <= item.maximum)
        ),
        None,
    )
    if row is None or column_index >= len(row.values):
        raise ValueError("These wages could not be matched to the table.")
    return row.values[column_index]
