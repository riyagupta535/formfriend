"""Local DOCX parsing and OCR; original PDF handling lives in parser.py."""
from io import BytesIO
import re
import json
import html
import textwrap
import zipfile
import xml.etree.ElementTree as ET
import pymupdf
from .models import FormField
from .ocr import extract_image_bundle, extract_image_fields

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def paragraphs(data):
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 30 * 1024 * 1024:
                raise ValueError('This Word document is too large when unpacked.')
            root = ET.fromstring(archive.read('word/document.xml'))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        raise ValueError('This Word document could not be read.') from None
    return root, list(root.iter(W + 'p'))

def extract_docx(data):
    _, items = paragraphs(data)
    fields = []
    for index, paragraph in enumerate(items):
        text = ''.join(node.text or '' for node in paragraph.iter(W + 't')).strip()
        if text and ('?' in text or ':' in text or re.search(r'_{3,}', text)):
            fields.append(FormField(field_id=f'docx:{index}', original_question=text[:1000], source_page=1, source_rect=[]))
    if not fields:
        raise ValueError('No question paragraphs found. Use a Word form with question marks, colons, or blank answer lines.')
    if len(fields) > 100:
        raise ValueError('Please use a form with 100 fields or fewer.')
    return fields

def extract_image(data):
    return extract_image_fields(data)

def extract_images(data):
    return extract_image_bundle(data)

def export_document(session, data):
    if session.document_type == 'pdf':
        with pymupdf.open(stream=data, filetype='pdf') as document:
            answers = {reference: field for field in session.fields
                       for reference in (field.widget_refs or [field.field_id]) if field.extraction == 'native'}
            for number, page in enumerate(document, 1):
                # Set off states first, then the selected radio, to preserve group selection.
                widgets = list(page.widgets() or [])
                for widget in widgets:
                    field = answers.get(f'p{number}:{widget.xref}')
                    if field is None:
                        continue
                    value = field.user_response or ''
                    if widget.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                        widget.field_value = False
                    elif widget.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                        widget.field_value = widget.on_state() if value == 'Yes' else 'Off'
                    elif field.answer_type == 'multichoice':
                        selected = json.loads(value) if value else []
                        selected = [option for option in field.options if option in selected]
                        # The high-level setter accepts scalars; multi-select uses
                        # AcroForm's value array and selected option indices.
                        document.xref_set_key(widget.xref, 'V', '[' + ' '.join(pymupdf.get_pdf_str(item) for item in selected) + ']')
                        indices = sorted(field.options.index(item) for item in selected)
                        document.xref_set_key(widget.xref, 'I', '[' + ' '.join(map(str, indices)) + ']')
                        document.xref_set_key(widget.xref, 'AP', 'null')
                        document.need_appearances(True)
                        continue
                    else:
                        widget.field_value = value
                    widget.update()
            for number, page in enumerate(document, 1):
                for widget in page.widgets() or []:
                    field = answers.get(f'p{number}:{widget.xref}')
                    if field and widget.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                        if field.user_response == str(widget.on_state()):
                            widget.field_value = widget.on_state()
                            widget.update()
            printed = [field for field in session.fields if field.extraction == 'printed']
            for field in printed:
                reference = f'original page {field.source_page}' if field.source_page > 0 else 'source page not provided'
                text = f'{field.original_question} ({reference})\n\n{field.user_response or "[No answer provided]"}'
                lines = []
                for line in text.splitlines():
                    lines.extend(textwrap.wrap(line, width=80) or [''])
                for start in range(0, len(lines), 38):
                    page = document.new_page(width=595, height=842)
                    content = html.escape('\n'.join(lines[start:start + 38]))
                    page.insert_htmlbox(pymupdf.Rect(42, 40, 553, 800),
                        '<h2>Form Friend — answer sheet</h2><p>Use with your original form. Check all answers before submission.</p>'
                        + '<pre>' + content + '</pre>',
                        css='body {font-family: sans-serif; font-size: 11pt;} pre {font-family: sans-serif; white-space: pre-wrap;}')
            return document.tobytes(), 'application/pdf'
    if session.document_type == 'docx':
        root, items = paragraphs(data)
        for field in session.fields:
            paragraph = items[int(field.field_id.split(':')[1])]
            run = ET.SubElement(paragraph, W + 'r')
            text = ET.SubElement(run, W + 't')
            text.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            text.text = ' ' + (field.user_response or '')
        output = BytesIO()
        with zipfile.ZipFile(BytesIO(data)) as original, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as filled:
            for item in original.infolist():
                filled.writestr(item, ET.tostring(root, encoding='utf-8', xml_declaration=True) if item.filename == 'word/document.xml' else original.read(item))
        return output.getvalue(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    text = '\n\n'.join(f'{field.original_question}\n{field.user_response or "[No answer provided]"}' for field in session.fields)
    return text.encode('utf-8'), 'text/plain; charset=utf-8'
