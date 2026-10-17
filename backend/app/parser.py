import pymupdf
from .models import FormField

def extract_fields(data: bytes) -> list[FormField]:
    """Phase 1 supports AcroForm text fields; never guess scanned fields."""
    fields = []
    with pymupdf.open(stream=data, filetype="pdf") as document:
        if document.needs_pass:
            raise ValueError("Please upload an unlocked PDF.")
        for page_number, page in enumerate(document, 1):
            for widget in page.widgets() or []:
                if widget.field_type != pymupdf.PDF_WIDGET_TYPE_TEXT:
                    raise ValueError("This PDF has non-text controls. Phase 1 supports text fields only.")
                label = widget.field_label or widget.field_name
                fields.append(FormField(field_id=f"p{page_number}:{widget.xref}",
                    original_question=label, source_page=page_number,
                    source_rect=list(widget.rect)))
    if not fields:
        raise ValueError("No fillable text fields found. Upload a fillable PDF; OCR is planned for a later phase.")
    if len(fields) > 100:
        raise ValueError("Please use a form with 100 fields or fewer for this demo.")
    return fields
