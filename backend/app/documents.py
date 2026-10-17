"""Local DOCX parsing and OCR; original PDF handling lives in parser.py."""
from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET
import pymupdf
from .models import FormField

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
    if not shutil.which('tesseract'):
        raise ValueError('Screenshot OCR requires Tesseract on the backend. Install Tesseract, or upload a fillable PDF or DOCX instead.')
    try:
        with pymupdf.open(stream=data) as image:
            page = image[0]
            if page.rect.width * page.rect.height > 25000000:
                raise ValueError('Please use a screenshot smaller than 25 megapixels.')
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'screenshot.png'
                page.get_pixmap().save(str(path))
                result = subprocess.run(['tesseract', str(path), 'stdout'], capture_output=True, text=True, timeout=40)
                if result.returncode:
                    raise ValueError('The screenshot could not be read. Try a clearer image.')
    except subprocess.TimeoutExpired:
        raise ValueError('OCR took too long. Try a smaller screenshot.') from None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    candidates = [line for line in lines if '?' in line or ':' in line or re.search(r'_{3,}', line)]
    if not candidates:
        raise ValueError('No questions found in this screenshot. Try a clear image with question labels, or upload the fillable version.')
    return [FormField(field_id=f'image:{i}', original_question=line[:1000], source_page=1, source_rect=[]) for i, line in enumerate(candidates[:100])]

def export_document(session, data):
    if session.document_type == 'pdf':
        with pymupdf.open(stream=data, filetype='pdf') as document:
            answers = {field.field_id: field.user_response or '' for field in session.fields}
            for number, page in enumerate(document, 1):
                for widget in page.widgets() or []:
                    key = f'p{number}:{widget.xref}'
                    if key in answers:
                        widget.field_value = answers[key]
                        widget.update()
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
