from dataclasses import dataclass
import re

import pymupdf

from .models import FormField


@dataclass
class OCRLine:
    text: str
    rect: pymupdf.Rect
    confidence: float


_NUMBERED = re.compile(r"^(\d+[a-z]?)[.)]?\s*(.*)$")
_LABELS = (
    ("businessname", "Business name/disregarded entity name, if different from above"),
    ("exemptpayeecode", "Exempt payee code (if any)"),
    ("exemptionfromforeignaccounttax", "Exemption from Foreign Account Tax Compliance Act (FATCA) reporting code (if any)"),
    ("requestersnameandaddress", "Requester's name and address (optional)"),
    ("citystateandzipcode", "City, state, and ZIP code"),
    ("listaccountnumbershere", "List account number(s) here (optional)"),
    ("socialsecuritynumber", "Social security number"),
    ("employeridentificationnumber", "Employer identification number"),
)


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _clean_ocr_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[,;:])(?=[A-Za-z])", " ", text)
    text = re.sub(r"(?<=[.!?])(?=[A-Z])", " ", text)
    return text


def _display_numbered_label(identifier: str, context: str, fallback: str) -> str:
    compact = _compact(context)
    known = (
        ("nameofentityindividual", "Name of entity/individual. An entry is required."),
        ("businessnamedisregardedentityname", "Business name/disregarded entity name, if different from above."),
        ("followingsevenboxes", "Check the appropriate box for federal tax classification."),
        ("addressnumberstreetandaptor", "Address (number, street, and apartment or suite number)."),
        ("citystateandzipcode", "City, state, and ZIP code."),
    )
    for signature, display in known:
        if signature in compact:
            return display
    if identifier.lower() == "3b" and "partnership" in compact and "taxclassification" in compact:
        return (
            "If line 3a is Partnership, Trust/estate, or an LLC taxed as a partnership, "
            "do you have an ownership interest in the recipient partnership, trust, or estate?"
        )
    return _clean_ocr_text(fallback)


def _union(lines: list[OCRLine]) -> pymupdf.Rect:
    rect = pymupdf.Rect(lines[0].rect)
    for line in lines[1:]:
        rect.include_rect(line.rect)
    return rect


def _ocr_page(page: pymupdf.Page) -> list[OCRLine]:
    # Imports stay lazy so text/fillable PDFs do not load the OCR runtime.
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    pixmap = page.get_pixmap(dpi=200, alpha=False, colorspace=pymupdf.csRGB)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )
    result, _ = RapidOCR()(image, return_word_box=True)
    scale_x = page.rect.width / pixmap.width
    scale_y = page.rect.height / pixmap.height
    lines = []
    for item in result or []:
        polygon, text, confidence = item[:3]
        if not text.strip():
            continue
        xs = [point[0] * scale_x for point in polygon]
        ys = [point[1] * scale_y for point in polygon]
        lines.append(OCRLine(
            text=_clean_ocr_text(text),
            rect=pymupdf.Rect(min(xs), min(ys), max(xs), max(ys)),
            confidence=float(confidence),
        ))
    return sorted(lines, key=lambda line: (line.rect.y0, line.rect.x0))


def _cutoff(lines: list[OCRLine], page_height: float) -> float:
    markers = ("generalinstructions", "specificinstructions", "partiicertification", "certification")
    matches = [line.rect.y0 for line in lines if any(
        _compact(line.text).startswith(marker) for marker in markers
    )]
    return min(matches, default=page_height)


def _numbered_fields(lines: list[OCRLine], page_number: int,
                     page_width: float, cutoff: float) -> list[FormField]:
    starts: list[tuple[OCRLine, str, str]] = []
    for line in lines:
        if line.rect.y0 >= cutoff:
            continue
        match = _NUMBERED.match(line.text)
        if not match or len(match.group(1)) > 3:
            continue
        identifier, label = match.groups()
        # Isolated page numbers and years are not form questions.
        if identifier.isdigit() and int(identifier) > 99:
            continue
        starts.append((line, identifier, label.strip()))

    fields = []
    used: set[int] = set()
    for index, (line, identifier, label) in enumerate(starts):
        if id(line) in used:
            continue
        next_y = min(
            (other.rect.y0 for other, _, _ in starts
             if other.rect.y0 > line.rect.y0 + 2 and
             abs(other.rect.x0 - line.rect.x0) <= page_width * .4),
            default=cutoff,
        )
        related = [line]
        if not label:
            nearby = [candidate for candidate in lines if candidate is not line and
                      abs(candidate.rect.y0 - line.rect.y0) <= 12 and
                      candidate.rect.x0 >= line.rect.x0 and
                      candidate.rect.x0 < page_width * .82 and
                      len(_compact(candidate.text)) > 4 and
                      _compact(candidate.text) not in {"page", "print", "type", "see"}]
            if nearby:
                selected = min(nearby, key=lambda candidate: (
                    candidate.rect.x0 - line.rect.x0,
                    abs(candidate.rect.y0 - line.rect.y0),
                ))
                label = selected.text
                related.append(selected)
        if not label or not re.search(r"[A-Za-z]", label):
            continue

        for candidate in lines:
            if candidate in related or candidate.rect.y0 <= line.rect.y0 + 2:
                continue
            continuation_depth = 80 if identifier.lower() in {"3", "3a"} else 34
            if candidate.rect.y0 >= min(next_y, line.rect.y0 + continuation_depth):
                continue
            same_column = (
                candidate.rect.x0 >= page_width * .6
                if line.rect.x0 >= page_width * .6
                else candidate.rect.x0 < page_width * .7
            )
            if same_column and re.search(r"[A-Za-z]", candidate.text):
                related.append(candidate)

        raw_context = " ".join(item.text for item in sorted(
            related, key=lambda item: (item.rect.y0, item.rect.x0)
        ))
        normalized = _compact(raw_context)
        options = []
        if identifier.lower() in {"3", "3a"} and "corporation" in normalized:
            choices = (
                ("individualsoleproprietor", "Individual/sole proprietor"),
                ("ccorporation", "C corporation"),
                ("scorporation", "S corporation"),
                ("partnership", "Partnership"),
                ("trustestate", "Trust/estate"),
                ("llc", "LLC"),
                ("other", "Other"),
            )
            options = [display for signature, display in choices if signature in normalized]
        confidence = sum(item.confidence for item in related) / len(related)
        rect = _union(related)
        fields.append(FormField(
            field_id=f"p{page_number}:ocr:{identifier.lower()}",
            question_number=identifier,
            original_question=f"{identifier} {_display_numbered_label(identifier, raw_context, label)}",
            answer_type="choice" if len(options) > 1 else "text",
            options=options,
            pdf_field_names=[],
            source_page=page_number,
            source_rect=list(rect),
            source_context=raw_context[:1000],
            extraction_confidence="medium" if confidence >= .85 else "low",
            source_kind="ocr",
            ocr_confidence=round(confidence, 4),
        ))
        used.update(id(item) for item in related)
    return fields


def _label_fields(lines: list[OCRLine], page_number: int, cutoff: float,
                  existing: list[FormField]) -> list[FormField]:
    fields = []
    seen = {_compact(field.original_question) for field in existing}
    for signature, display in _LABELS:
        matches = [line for line in lines if line.rect.y0 < cutoff and signature in _compact(line.text)]
        if not matches or any(signature in value for value in seen):
            continue
        line = min(matches, key=lambda candidate: (len(_compact(candidate.text)), candidate.rect.y0))
        key = re.sub(r"[^a-z0-9]+", "-", display.lower()).strip("-")[:40]
        fields.append(FormField(
            field_id=f"p{page_number}:ocr:{key}",
            original_question=display,
            answer_type="text",
            options=[],
            pdf_field_names=[],
            source_page=page_number,
            source_rect=list(line.rect),
            source_context=line.text[:1000],
            extraction_confidence="medium" if line.confidence >= .85 else "low",
            source_kind="ocr",
            ocr_confidence=round(line.confidence, 4),
        ))
    return fields


def extract_ocr_fields(document: pymupdf.Document) -> list[FormField]:
    """OCR image-only pages and conservatively return question-like fields.

    The prototype stops after the first page with at least three numbered fields.
    This avoids OCRing instruction appendices such as the remaining W-9 pages.
    """
    for page_number, page in enumerate(document, 1):
        lines = _ocr_page(page)
        cutoff = _cutoff(lines, page.rect.height)
        fields = _numbered_fields(lines, page_number, page.rect.width, cutoff)
        if len(fields) >= 3:
            label_fields = _label_fields(lines, page_number, cutoff, fields)
            if label_fields:
                fields = [field for field in fields if not (
                    field.question_number == "4" and
                    "exemptions" in _compact(field.original_question)
                )]
            fields.extend(label_fields)
            fields.sort(key=lambda field: (field.source_rect[1], field.source_rect[0]))
            return fields[:100]
    return []
