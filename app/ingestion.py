from __future__ import annotations

import re
from pathlib import Path

from .models import Page


class ExtractionError(RuntimeError):
    """Raised when a PDF cannot be read or has no useful text."""


def extract_pages(path: str | Path, document_id: str) -> list[Page]:
    """Extract text page-by-page and preserve the source page boundaries."""
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - exercised in setup failures
        raise ExtractionError("PyMuPDF is required for PDF extraction") from exc

    pdf_path = Path(path)
    try:
        document = fitz.open(pdf_path)
    except Exception as exc:  # pragma: no cover - depends on malformed PDFs
        raise ExtractionError(f"Could not open PDF: {exc}") from exc

    pages: list[Page] = []
    try:
        for index, page in enumerate(document):
            text = page.get_text("text").strip()
            # A page with no selectable text is retained so OCR need is visible.
            pages.append(
                Page(
                    document_id=document_id,
                    page_number=index + 1,
                    text=text,
                    is_scanned=not bool(re.search(r"\w", text)),
                )
            )
    finally:
        document.close()

    if not pages:
        raise ExtractionError("PDF contains no pages")
    return pages


def verify_evidence(page: Page, quote: str) -> tuple[bool, int | None, int | None]:
    """Verify a model-provided quote against extracted page text."""
    if not quote or not page.text:
        return False, None, None
    start = page.text.casefold().find(quote.casefold())
    if start < 0:
        return False, None, None
    return True, start, start + len(quote)