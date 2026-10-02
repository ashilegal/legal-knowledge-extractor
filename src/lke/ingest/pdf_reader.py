"""Page text + font info (PyMuPDF)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pymupdf

from lke.models import TextLine

if hasattr(pymupdf, "no_recommend_layout"):      # silence an advert printed by find_tables
    pymupdf.no_recommend_layout()


class UnreadablePdfError(Exception):
    """The PDF is corrupt, encrypted or otherwise cannot be opened."""


def open_pdf(path: Path) -> pymupdf.Document:
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # PyMuPDF raises several error types for broken files
        raise UnreadablePdfError(f"cannot open PDF: {e}") from e
    if doc.needs_pass:
        doc.close()
        raise UnreadablePdfError("PDF is password protected")
    if doc.page_count == 0:
        doc.close()
        raise UnreadablePdfError("PDF has no pages")
    return doc


def page_lines(page: pymupdf.Page, textpage: pymupdf.TextPage | None = None) -> list[TextLine]:
    """Lines in reading order, each with its biggest font size and bold flag."""
    data = page.get_text("dict", sort=True, textpage=textpage)
    height = page.rect.height or 1.0
    lines: list[TextLine] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:          # 0 = text, 1 = image
            continue
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in line["spans"]).strip()
            size = max(s.get("size", 0.0) for s in spans)
            # flags bit 16 = bold; some fonts only say "Bold" in their name
            bold = all(
                (s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower() for s in spans
            )
            lines.append(TextLine(text=text, size=round(size, 1), bold=bool(bold),
                                  y=round(line["bbox"][1] / height, 3)))
    return lines


def page_tables(page: pymupdf.Page) -> list[list[list[str]]]:
    """Tables found on the page, as rows of cell strings. Empty list if none."""
    try:
        found = page.find_tables()
    except Exception:                   # table detection is best-effort
        return []
    tables: list[list[list[str]]] = []
    for table in found.tables:
        rows = [[" ".join((cell or "").split()) for cell in row] for row in table.extract()]
        rows = [r for r in rows if any(r)]
        if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
            tables.append(rows)
    return tables


def image_coverage(page: pymupdf.Page) -> float:
    """Share of the page area covered by images (scanned pages are close to 1.0)."""
    page_area = abs(page.rect) or 1.0
    covered = 0.0
    for info in page.get_image_info():
        covered += abs(pymupdf.Rect(info["bbox"]) & page.rect)
    return min(covered / page_area, 1.0)


def iter_pages(doc: pymupdf.Document) -> Iterator[tuple[int, pymupdf.Page]]:
    """(1-based page number, page) one at a time, so large PDFs are never fully in memory."""
    for index in range(doc.page_count):
        yield index + 1, doc.load_page(index)
