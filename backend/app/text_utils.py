import re


_LEADING_FORM_REFERENCE = re.compile(
    r"""^\s*(?:
        (?:(?:question|item|line|part|step)\s+(?:\d{1,3}(?:\s*\(\s*[a-z0-9ivxlcdm]+\s*\)|[a-z])?|[a-z]))
        |(?:\(\s*[a-z0-9ivxlcdm]+\s*\))
        |(?:\d{1,3}(?:\s*\(\s*[a-z0-9ivxlcdm]+\s*\)|[a-z])?)
    )(?:\s*[.):·—–-]\s*|\s+)""",
    re.IGNORECASE | re.VERBOSE,
)


def strip_form_reference(text: str) -> str:
    """Remove a leading printed question/line label without changing source wording."""
    cleaned = text.strip()
    while True:
        updated = _LEADING_FORM_REFERENCE.sub("", cleaned, count=1).strip()
        if updated == cleaned or not updated:
            return cleaned
        cleaned = updated
