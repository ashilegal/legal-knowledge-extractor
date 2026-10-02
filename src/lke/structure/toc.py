"""Use PDF bookmarks if present."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass
class TocEntry:
    level: int                        # 1 = top level
    title: str
    page: int                         # 1-based


def read_toc(pdf_path: Path) -> list[TocEntry]:
    """Bookmarks stored in the PDF. Returns [] if the file has none or cannot be read."""
    if not pdf_path.exists():
        return []
    try:
        with pymupdf.open(pdf_path) as doc:
            raw = doc.get_toc(simple=True)
            page_count = doc.page_count
    except Exception:
        return []
    entries = []
    for level, title, page in raw:
        title = " ".join(str(title).split())
        if title and 1 <= page <= page_count:
            entries.append(TocEntry(level=int(level), title=title, page=int(page)))
    return entries
