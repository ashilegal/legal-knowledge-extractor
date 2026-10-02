"""Detect scanned pages, OCR only those."""

from __future__ import annotations

import regex as re
import pymupdf

from lke.ingest.pdf_reader import image_coverage, page_lines
from lke.models import TextLine

_WORD = re.compile(r"\p{L}{2,}")
_TOKEN = re.compile(r"\S+")


class OcrUnavailableError(Exception):
    """Tesseract is not installed or its language data cannot be found."""


def needs_ocr(page: pymupdf.Page, text: str, min_chars: int) -> bool:
    """Little or no text, but the page is mostly an image -> it is a scan."""
    if len(text.strip()) >= min_chars:
        return False
    return image_coverage(page) > 0.3


def text_quality(text: str) -> float:
    """Rough 0..1 score: share of tokens that look like real words (low = bad OCR)."""
    tokens = _TOKEN.findall(text)
    if not tokens:
        return 0.0
    good = sum(1 for t in tokens if _WORD.search(t))
    return round(good / len(tokens), 3)


def ocr_page(page: pymupdf.Page, language: str = "eng", dpi: int = 300) -> list[TextLine]:
    """Run Tesseract on one page through PyMuPDF and return its lines."""
    try:
        textpage = page.get_textpage_ocr(language=language, dpi=dpi, full=True)
    except Exception as e:
        raise OcrUnavailableError(
            f"OCR failed ({e}). Is Tesseract installed and TESSDATA_PREFIX set?"
        ) from e
    return page_lines(page, textpage=textpage)
