from collections import defaultdict
from dataclasses import dataclass
import re

import pymupdf

from .models import FormField


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


_SUPPORTED_TYPES = {
    pymupdf.PDF_WIDGET_TYPE_TEXT,
    pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
    pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
    pymupdf.PDF_WIDGET_TYPE_LISTBOX,
}
_INTERNAL_NAME = re.compile(r"(?:^|\.)(?:f|c)\d+_\d+\[\d+\]$", re.IGNORECASE)


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
    if any(word in lowered for word in ("number of", "count", "how many")):
        return "number"
    return "text"


def _checkbox_group_name(name: str) -> str:
    return re.sub(r"\[\d+\]$", "", name)


def _union(rects: list[pymupdf.Rect]) -> pymupdf.Rect:
    result = pymupdf.Rect(rects[0])
    for rect in rects[1:]:
        result.include_rect(rect)
    return result


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
        raise ValueError("No fillable fields we can support were found. Upload a fillable PDF; OCR is planned for a later phase.")

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
    return fields
