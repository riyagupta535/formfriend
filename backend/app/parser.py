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
    flags: int
    choices: list[str]
    on_state: str | None


@dataclass
class PDFExtraction:
    fields: list[FormField]
    warnings: list[str]


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


def _simple_printed_fields(document: pymupdf.Document) -> list[FormField]:
    fields = []
    label = re.compile(
        r'^(?:\d+[.)]?\s*)?(?:full name|first name|last name|name|date of birth|'
        r'birth date|address|street address|city|state|zip(?: code)?|postal code|'
        r'email(?: address)?|phone(?: number)?|telephone|signature|date)\s*[:_]*$', re.I
    )
    for page_number, page in enumerate(document, 1):
        for index, line in enumerate(_logical_lines(page)):
            text = line.text.strip()
            if not text.lower().startswith('signature') and (
                '?' in text or (':' in text and '://' not in text)
                or re.search(r'_{3,}', text) or label.fullmatch(text)
            ):
                fields.append(FormField(
                    field_id=f'printed:{page_number}:{index}',
                    original_question=text[:1000], source_page=page_number,
                    source_rect=list(line.rect), source_context=text[:1000],
                    extraction='printed', source_kind='text-layer',
                ))
    return fields


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
                extraction="printed",
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
                extraction="printed",
            ))

    fields.sort(key=lambda field: (field.source_page, field.source_rect[1], field.source_rect[0]))
    return fields


def _extract_fields(data: bytes, warnings: list[str]) -> list[FormField]:
    """Extract supported fillable fields and their nearby source text.

    This is deliberately deterministic. The parser gathers evidence for an LLM but
    does not ask an LLM to discover fields or invent labels.
    """
    extracted: list[_ExtractedWidget] = []
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("Please upload an unlocked PDF.")
        if len(document) > 30:
            raise ValueError("Please split this PDF into documents of 30 pages or fewer.")
        for page_number, page in enumerate(document, 1):
            widgets = []
            for widget in page.widgets() or []:
                if widget.field_flags & pymupdf.PDF_FIELD_IS_READ_ONLY:
                    warnings.append('Read-only PDF fields are preserved and cannot be edited here.')
                    continue
                if widget.field_type not in _SUPPORTED_TYPES:
                    warnings.append('Signature fields and action buttons are preserved. Complete signatures separately after downloading.')
                    continue
                widgets.append(widget)
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
                    flags=widget.field_flags,
                    choices=[str(value[0] if isinstance(value, (tuple, list)) else value)
                             for value in widget.choice_values or []],
                    on_state=str(widget.on_state()) if widget.field_type in {
                        pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                        pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON,
                    } else None,
                ))

        if not extracted:
            text_fields = _extract_text_layer_fields(document)
            if not text_fields:
                text_fields = _simple_printed_fields(document)
            if text_fields:
                if len(text_fields) > 100:
                    raise ValueError("Please use a form with 100 fields or fewer for this demo.")
                return text_fields
            from .ocr import extract_ocr_fields
            ocr_fields = extract_ocr_fields(document) if any(page.get_images() for page in document) else []
            if ocr_fields:
                for field in ocr_fields:
                    field.extraction = 'printed'
                warnings.append('Scanned pages were read using OCR. Check extracted questions against the page preview.')
                return ocr_fields

    if not extracted:
        raise ValueError(
            "No questions, fillable fields, or recognizable scanned prompts were found."
        )

    checkbox_groups: dict[tuple[int, str] | tuple[str, str], list[_ExtractedWidget]] = defaultdict(list)
    ungrouped = []
    for item in extracted:
        if item.field_type in {pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                               pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON}:
            key = ("radio", item.name) if item.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON else (
                item.page_number, _checkbox_group_name(item.name)
            )
            checkbox_groups[key].append(item)
        else:
            ungrouped.append(item)

    fields: list[FormField] = []
    for item in ungrouped:
        options = item.choices
        answer_type = _answer_type(item.label, item.field_type)
        if item.field_type == pymupdf.PDF_WIDGET_TYPE_LISTBOX and item.flags & pymupdf.PDF_CH_FIELD_IS_MULTI_SELECT:
            answer_type = 'multichoice'
        fields.append(FormField(
            field_id=f"p{item.page_number}:{item.xref}",
            question_number=_question_number(f"{item.label} {item.context}"),
            section_title=_step_section_title(item.context),
            original_question=item.label,
            answer_type=answer_type,
            options=options,
            pdf_field_names=[item.name],
            widget_refs=[f'p{item.page_number}:{item.xref}'],
            source_page=item.page_number,
            source_rect=list(item.rect),
            source_context=item.context,
            extraction_confidence=item.confidence,
        ))

    for (_, _), items in checkbox_groups.items():
        items.sort(key=lambda item: (item.rect.y0, item.rect.x0))
        grouped = len(items) > 1
        options = ([item.on_state or item.label for item in items]
                   if items[0].field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON
                   else [item.label for item in items] if grouped else ['Yes', 'No'])
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
            widget_refs=[f'p{item.page_number}:{item.xref}' for item in items],
            source_page=items[0].page_number,
            source_rect=list(rect),
            source_context=context,
            extraction_confidence="medium",
        ))

    fields.sort(key=lambda field: (field.source_page, field.source_rect[1], field.source_rect[0]))
    if len(fields) > 100:
        raise ValueError("Please use a form with 100 fields or fewer for this demo.")
    return fields


def extract_pdf(data: bytes) -> PDFExtraction:
    warnings: list[str] = []
    fields = _extract_fields(data, warnings)
    if any(field.extraction == 'printed' for field in fields):
        warnings.append(
            'Printed or scanned questions are detected heuristically. Their answers are appended '
            'as a PDF answer sheet rather than placed into guessed positions.'
        )
    return PDFExtraction(fields, list(dict.fromkeys(warnings)))


def extract_fields(data: bytes) -> list[FormField]:
    return extract_pdf(data).fields
