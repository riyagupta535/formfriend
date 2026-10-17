"""Extract native PDF controls, printed questions, and scanned questions."""
import csv
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import pymupdf
from .models import FormField

MAX_PAGES = 30
MAX_FIELDS = 100
LABEL = re.compile(
    r'^(?:\d+[.)]\s*)?(?:full name|first name|last name|name|date of birth|'
    r'birth date|address|street address|city|state|zip(?: code)?|postal code|'
    r'email(?: address)?|phone(?: number)?|telephone|signature|date)\s*[:_]*$', re.I)


@dataclass
class PDFExtraction:
    fields: list[FormField]
    warnings: list[str]


def is_question(text: str) -> bool:
    text = text.strip()
    return bool(text and (('?' in text or (':' in text and '://' not in text)) or re.search(r'_{3,}', text)
                         or LABEL.fullmatch(text)))


def page_lines(page):
    lines = []
    for block in page.get_text('dict', sort=True)['blocks']:
        for line in block.get('lines', []):
            text = ' '.join(span['text'] for span in line['spans']).strip()
            if text:
                lines.append((text, list(line['bbox'])))
    return lines


def ocr_lines(page):
    if not shutil.which('tesseract'):
        raise ValueError('This PDF contains scanned pages. Install Tesseract on the backend for OCR, or upload a PDF with selectable text.')
    # Bound raster memory while keeping normal pages near 180 dpi.
    scale = min(2.5, (6000000 / max(page.rect.get_area(), 1)) ** .5)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'page.png'
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
        pixmap.save(str(path))
        try:
            result = subprocess.run(['tesseract', str(path), 'stdout', 'tsv'],
                                    capture_output=True, text=True, timeout=40)
        except subprocess.TimeoutExpired:
            raise ValueError('OCR took too long. Try a shorter PDF or clearer scan.') from None
        if result.returncode:
            raise ValueError('A scanned PDF page could not be read. Try a clearer scan.')
    groups = {}
    for row in csv.DictReader(StringIO(result.stdout), delimiter='\t'):
        if row.get('level') != '5' or not row.get('text', '').strip():
            continue
        key = (row['block_num'], row['par_num'], row['line_num'])
        x, y, w, h = (float(row[name]) for name in ('left', 'top', 'width', 'height'))
        rect = pymupdf.Rect(x / scale, y / scale, (x + w) / scale, (y + h) / scale)
        text, bounds = groups.setdefault(key, ([], pymupdf.Rect(rect)))
        text.append(row['text'])
        bounds.include_rect(rect)
    return [(' '.join(text), list(rect)) for text, rect in groups.values()]


def extract_pdf(data: bytes) -> PDFExtraction:
    fields, warnings = [], []
    radios = {}
    with pymupdf.open(stream=data, filetype='pdf') as document:
        if document.needs_pass:
            raise ValueError('Please upload an unlocked PDF. Password-protected files cannot be read yet.')
        if len(document) > MAX_PAGES:
            raise ValueError(f'Please split this PDF into documents of {MAX_PAGES} pages or fewer.')
        for number, page in enumerate(document, 1):
            native = False
            for widget in page.widgets() or []:
                kind = widget.field_type
                if widget.field_flags & pymupdf.PDF_FIELD_IS_READ_ONLY:
                    warnings.append('Read-only PDF fields are preserved and cannot be edited here.')
                    continue
                if kind not in (pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.PDF_WIDGET_TYPE_CHECKBOX,
                                pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON, pymupdf.PDF_WIDGET_TYPE_COMBOBOX,
                                pymupdf.PDF_WIDGET_TYPE_LISTBOX):
                    warnings.append('Signature fields and action buttons are preserved. Complete signatures separately after downloading.')
                    continue
                native = True
                reference = f'p{number}:{widget.xref}'
                label = widget.field_label or widget.field_name or f'Field {len(fields) + 1}'
                answer_type, options = 'text', []
                if kind == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                    answer_type, options = 'checkbox', ['Yes', 'No']
                elif kind == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                    answer_type = 'choice'
                    option = str(widget.on_state())
                    if widget.field_name in radios:
                        group = radios[widget.field_name]
                        if option not in group.options:
                            group.options.append(option)
                        group.widget_refs.append(reference)
                        continue
                    options = [option]
                elif kind in (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX):
                    answer_type = 'multichoice' if widget.field_flags & pymupdf.PDF_CH_FIELD_IS_MULTI_SELECT else 'choice'
                    options = [str(item[0] if isinstance(item, (tuple, list)) else item)
                               for item in widget.choice_values or []]
                field = FormField(field_id=reference, original_question=label,
                                  answer_type=answer_type, options=options,
                                  source_page=number, source_rect=list(widget.rect),
                                  widget_refs=[reference])
                fields.append(field)
                if kind == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                    radios[widget.field_name] = field
            # Pages with native fields use the native labels, avoiding duplicate questions.
            if native:
                continue
            lines = page_lines(page)
            if not any(is_question(text) for text, _ in lines) and page.get_images():
                lines = ocr_lines(page)
                warnings.append('Scanned pages were read using OCR. Check extracted questions against the page preview.')
            for i, (text, rect) in enumerate(lines):
                if is_question(text) and not text.lower().startswith('signature'):
                    fields.append(FormField(field_id=f'printed:{number}:{i}', original_question=text[:1000],
                                            source_page=number, source_rect=rect, extraction='printed'))
    if not fields:
        raise ValueError('No questions found in this PDF. Try a clearer scan or a form with visible question labels. Image-only PDFs require Tesseract OCR.')
    if len(fields) > MAX_FIELDS:
        raise ValueError(f'Please split this PDF into forms with {MAX_FIELDS} questions or fewer.')
    if any(field.extraction == 'printed' for field in fields):
        warnings.append('Printed or scanned questions are detected from labels and punctuation. Answers for these questions are appended as a PDF answer sheet; they are not placed into guessed positions on the original pages.')
    return PDFExtraction(fields, list(dict.fromkeys(warnings)))


def extract_fields(data: bytes) -> list[FormField]:
    return extract_pdf(data).fields
