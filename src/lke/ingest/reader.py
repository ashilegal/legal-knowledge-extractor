"""Read one PDF into cleaned pages: text extraction, OCR where needed, clean-up."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lke.config import Settings
from lke.ingest.cleaner import clean_pages
from lke.ingest.ocr import OcrUnavailableError, needs_ocr, ocr_page, text_quality
from lke.ingest.pdf_reader import iter_pages, open_pdf, page_lines, page_tables
from lke.models import Page

LOW_OCR_QUALITY = 0.6


@dataclass
class IngestResult:
    doc_id: str
    page_count: int
    pages: list[Page]
    ocr_pages: list[int] = field(default_factory=list)
    ocr_failed_pages: list[int] = field(default_factory=list)
    low_quality_pages: list[int] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)
    table_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def ingest_pdf(path: Path, doc_id: str, settings: Settings) -> IngestResult:
    """Raises UnreadablePdfError for corrupt/encrypted files (caller quarantines them)."""
    ocr_cfg = settings.ocr
    raw_pages: list[Page] = []
    result = IngestResult(doc_id=doc_id, page_count=0, pages=[])
    ocr_available = ocr_cfg.enabled

    with open_pdf(path) as doc:
        result.page_count = doc.page_count
        for number, page in iter_pages(doc):
            lines = page_lines(page)
            text = "\n".join(l.text for l in lines)
            is_ocr = False
            quality: float | None = None

            if ocr_available and needs_ocr(page, text, ocr_cfg.min_chars_per_page):
                try:
                    lines = ocr_page(page, language=ocr_cfg.language)
                    text = "\n".join(l.text for l in lines)
                    is_ocr = True
                    quality = text_quality(text)
                    result.ocr_pages.append(number)
                    if quality < LOW_OCR_QUALITY:
                        result.low_quality_pages.append(number)
                except OcrUnavailableError as e:
                    ocr_available = False           # don't retry on every page
                    result.ocr_failed_pages.append(number)
                    result.warnings.append(str(e))
            elif not ocr_available and needs_ocr(page, text, ocr_cfg.min_chars_per_page):
                result.ocr_failed_pages.append(number)

            tables = page_tables(page) if settings.tables.enabled and not is_ocr else []
            if tables:
                result.table_pages.append(number)

            raw_pages.append(Page(
                doc_id=doc_id, page_number=number, text=text, char_count=len(text),
                is_ocr=is_ocr, ocr_confidence=quality, lines=lines, tables=tables,
            ))

    result.pages = clean_pages(raw_pages)
    result.empty_pages = [p.page_number for p in result.pages if p.char_count == 0]
    return result
