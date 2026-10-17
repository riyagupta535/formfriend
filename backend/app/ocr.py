from dataclasses import dataclass
from difflib import SequenceMatcher
from io import BytesIO
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


def _run_ocr(image, logical_width: float, logical_height: float) -> list[OCRLine]:
    from rapidocr_onnxruntime import RapidOCR

    result, _ = RapidOCR()(image, return_word_box=True)
    scale_x = logical_width / image.shape[1]
    scale_y = logical_height / image.shape[0]
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


def _ocr_page(page: pymupdf.Page) -> list[OCRLine]:
    # Imports stay lazy so text/fillable PDFs do not load the OCR runtime.
    import numpy as np

    pixmap = page.get_pixmap(dpi=200, alpha=False, colorspace=pymupdf.csRGB)
    image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )
    return _run_ocr(image, page.rect.width, page.rect.height)


def _ocr_image(data: bytes) -> tuple[list[OCRLine], int, int]:
    import numpy as np
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source)
            width, height = image.size
            if width * height > 25_000_000:
                raise ValueError("Please use a screenshot smaller than 25 megapixels.")
            pixels = np.asarray(image.convert("RGB"))
    except (UnidentifiedImageError, OSError):
        raise ValueError("This screenshot could not be read. Try a PNG or JPG image.") from None
    return _run_ocr(pixels, width, height), width, height


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
                      candidate.rect.x0 < page_width * .82 and
                      len(_compact(candidate.text)) > 4 and
                      _compact(candidate.text) not in {"page", "print", "type", "see"}]
            if nearby:
                selected = min(nearby, key=lambda candidate: (
                    min(abs(candidate.rect.x0 - line.rect.x1),
                        abs(line.rect.x0 - candidate.rect.x1)),
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


def _make_image_field(key: str, question: str, lines: list[OCRLine], *,
                      question_number: str | None = None,
                      section_title: str | None = None,
                      answer_type: str = "text", options: list[str] | None = None) -> FormField:
    confidence = sum(line.confidence for line in lines) / len(lines)
    return FormField(
        field_id=f"image:ocr:{key}",
        question_number=question_number,
        section_title=section_title,
        original_question=question,
        answer_type=answer_type,
        options=options or [],
        pdf_field_names=[],
        source_page=1,
        source_rect=list(_union(lines)),
        source_context=" ".join(line.text for line in lines)[:1000],
        extraction_confidence="medium" if confidence >= .85 else "low",
        source_kind="ocr",
        ocr_confidence=round(confidence, 4),
    )


def _first_match(lines: list[OCRLine], signature: str) -> OCRLine | None:
    return next((line for line in lines if signature in _compact(line.text)), None)


def _screenshot_label_fields(lines: list[OCRLine]) -> list[FormField]:
    labels = (
        ("yourfirstnameandmiddleinitial", "your-name", "Your first name and middle initial"),
        ("yoursocialsecuritynumber", "your-ssn", "Your social security number"),
        ("ifjointreturnspousesfirstname", "spouse-name", "Spouse's first name and middle initial"),
        ("spousessocialsecuritynumber", "spouse-ssn", "Spouse's social security number"),
        ("homeaddressnumberandstreet", "home-address", "Home address (number and street)"),
        ("aptno", "apartment", "Apartment number"),
        ("citytownorpostoffice", "city", "City, town, or post office"),
        ("foreigncountryname", "foreign-country", "Foreign country name"),
        ("foreignprovincestatecounty", "foreign-region", "Foreign province, state, or county"),
        ("foreignpostalcode", "foreign-postal-code", "Foreign postal code"),
    )
    fields = []
    for signature, key, display in labels:
        line = _first_match(lines, signature)
        if line:
            fields.append(_make_image_field(key, display, [line]))

    name_lines = [line for line in lines if _compact(line.text) == "lastname"]
    for index, line in enumerate(name_lines[:2]):
        owner = "Your" if index == 0 else "Spouse's"
        fields.append(_make_image_field(
            f"{'your' if index == 0 else 'spouse'}-last-name", f"{owner} last name", [line]
        ))

    state = next((line for line in lines if _compact(line.text) == "state"), None)
    zip_code = next((line for line in lines if _compact(line.text) == "zipcode"), None)
    if state:
        fields.append(_make_image_field("state", "State", [state]))
    if zip_code:
        fields.append(_make_image_field("zip-code", "ZIP code", [zip_code]))

    qualifying_name = _first_match(lines, "qualifyingpersonisachildbutnotyourdependent")
    if qualifying_name:
        fields.append(_make_image_field(
            "qualifying-person-name", "Qualifying person's name (if required)",
            [qualifying_name], section_title="Filing Status",
        ))
    nonresident_name = _first_match(lines, "name see instructions and attach statement if required")
    if nonresident_name:
        fields.append(_make_image_field(
            "nonresident-spouse-name",
            "Nonresident or dual-status alien spouse name (if required)",
            [nonresident_name], section_title="Filing Status",
        ))

    filing = _first_match(lines, "filingstatus")
    if filing:
        choices = (
            ("single", "Single"),
            ("marriedfilingjointly", "Married filing jointly"),
            ("marriedfilingseparately", "Married filing separately"),
            ("headofhousehold", "Head of household"),
            ("qualifyingsurvivingspouse", "Qualifying surviving spouse"),
        )
        options = [display for signature, display in choices if _first_match(lines, signature)]
        fields.append(_make_image_field(
            "filing-status", "Filing status", [filing],
            section_title="Filing Status", answer_type="choice", options=options,
        ))

    digital_continuation = _first_match(lines, "exchangeorotherwisedisposeofadigitalasset")
    digital = _first_match(lines, "atanytimeduring") or digital_continuation
    if digital and ("digitalasset" in _compact(digital.text) or digital_continuation):
        evidence = [digital]
        if digital_continuation and digital_continuation is not digital:
            evidence.append(digital_continuation)
        fields.append(_make_image_field(
            "digital-assets",
            "During the tax year, did you receive, sell, exchange, or otherwise dispose of a digital asset?",
            evidence, section_title="Digital Assets", answer_type="choice", options=["Yes", "No"],
        ))

    dependent_headers = [line for line in lines if re.fullmatch(r"dependent[1-4]", _compact(line.text))]
    dependent_rows = (
        ("1", "firstname", "First name"),
        ("2", "lastname", "Last name"),
        ("3", "ssn", "Social security number"),
        ("4", "relationship", "Relationship"),
    )
    for header in dependent_headers:
        number = re.search(r"[1-4]", _compact(header.text)).group()
        for row_number, signature, display in dependent_rows:
            row = next((line for line in lines if
                        re.match(rf"^\({row_number}\)\s*", line.text) and
                        signature in _compact(line.text)), None)
            if row:
                fields.append(_make_image_field(
                    f"dependent-{number}-{signature}", f"Dependent {number}: {display}",
                    [header, row], question_number=row_number, section_title="Dependents",
                ))
    return fields


def extract_image_fields(data: bytes) -> list[FormField]:
    lines, width, height = _ocr_image(data)
    if not lines:
        raise ValueError("No readable text was found in this screenshot. Try a clearer image.")

    fields = _numbered_fields(lines, 1, width, height)
    ignored_option_labels = {
        "line3b", "rollover", "qcd", "pso",
    }
    fields = [field for field in fields if not (
        _compact(re.sub(r"^\d+[a-z]?\s*", "", field.original_question)) in ignored_option_labels
        or "yourchildsdividendsareincluded" in _compact(field.original_question)
    )]
    fields.extend(_screenshot_label_fields(lines))

    # Retain general form prompts even when they do not use numbered labels.
    for index, line in enumerate(lines):
        text = line.text.strip()
        if not ("?" in text or text.endswith(":") or re.search(r"_{3,}", text)):
            continue
        if (len(text) > 500 or not re.search(r"[A-Za-z]", text) or
                (text.endswith(":") and not text[0].isupper())):
            continue
        if any(_compact(text) in _compact(field.source_context) for field in fields):
            continue
        fields.append(_make_image_field(f"prompt-{index}", text[:500], [line]))

    unique = []
    seen = set()
    line_id_counts: dict[str, int] = {}
    for field in sorted(fields, key=lambda item: (item.source_rect[1], item.source_rect[0])):
        label = re.sub(r"^\d+[a-z]?\s*", "", field.original_question)
        signature = (round(field.source_rect[1] / 6), _compact(label))
        if signature in seen:
            continue
        seen.add(signature)
        if field.field_id.startswith("p1:ocr:"):
            base = f"image:ocr:line-{field.question_number.lower()}"
            line_id_counts[base] = line_id_counts.get(base, 0) + 1
            suffix = f"-{line_id_counts[base]}" if line_id_counts[base] > 1 else ""
            field.field_id = base + suffix
        unique.append(field)
    if not unique:
        raise ValueError(
            "No form questions were found in this screenshot. Try a clearer image or a tighter crop."
        )
    return unique[:100]


def _field_text(field: FormField) -> str:
    return _compact(re.sub(r"^\d+[a-z]?\s*", "", field.original_question))


def _same_question(first: FormField, second: FormField) -> bool:
    if first.section_title and second.section_title and first.section_title != second.section_title:
        return False
    if first.question_number and second.question_number and first.question_number != second.question_number:
        return False
    first_text, second_text = _field_text(first), _field_text(second)
    if first_text == second_text:
        return True
    shorter, longer = sorted((first_text, second_text), key=len)
    if len(shorter) < 12:
        return False
    if shorter in longer and len(shorter) / len(longer) >= .78:
        return True
    return SequenceMatcher(None, first_text, second_text).ratio() >= .9


def _field_quality(field: FormField) -> tuple[float, int]:
    return (field.ocr_confidence or 0, len(_field_text(field)))


def deduplicate_image_fields(pages: list[list[FormField]]) -> tuple[list[FormField], int]:
    """Merge overlapping screenshot fields, retaining the strongest OCR copy."""
    merged: list[FormField] = []
    removed = 0
    for page_number, page_fields in enumerate(pages, 1):
        for field in page_fields:
            field.source_page = page_number
            duplicate_index = next(
                (index for index, existing in enumerate(merged) if _same_question(existing, field)),
                None,
            )
            if duplicate_index is None:
                merged.append(field)
                continue
            removed += 1
            if _field_quality(field) > _field_quality(merged[duplicate_index]):
                merged[duplicate_index] = field

    id_counts: dict[str, int] = {}
    for field in merged:
        identity = field.question_number or _field_text(field)[:48] or "field"
        slug = re.sub(r"[^a-z0-9]+", "-", identity.lower()).strip("-") or "field"
        base = f"image:ocr:{slug}"
        id_counts[base] = id_counts.get(base, 0) + 1
        suffix = f"-{id_counts[base]}" if id_counts[base] > 1 else ""
        field.field_id = base + suffix
    if len(merged) > 100:
        raise ValueError("Please use screenshots containing 100 questions or fewer.")
    return merged, removed


def extract_image_bundle(images: list[bytes]) -> tuple[list[FormField], int]:
    if not images:
        raise ValueError("Choose at least one screenshot.")
    if len(images) > 10:
        raise ValueError("Upload no more than 10 screenshots for one form.")
    return deduplicate_image_fields([extract_image_fields(image) for image in images])


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
