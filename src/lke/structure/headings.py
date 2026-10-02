"""Detect headings by font size/bold/numbering."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import regex as re

from lke.ingest.cleaner import is_page_number
from lke.models import Page, TextLine

MAX_HEADING_CHARS = 120
MAX_HEADING_WORDS = 16
SIZE_RATIO = 1.12                     # 12% bigger than body text counts as "bigger"

_NUMBERING = re.compile(
    r"""^(?:
        (?:chapter|part|unit|module|title|book|section|article|schedule|appendix)
            \s+(?:\d+|[ivxlcdm]+|[a-z])\b          # Chapter 3, Part II, Appendix A
      | (?P<dotted>\d+(?:\.\d+){0,4})\.?\s+\S      # 3  /  3.4  /  3.4.1
      | [A-Z]\.\s+\S                               # A. Something
      | [IVXLC]+\.\s+\S                            # IV. Something
    )""",
    re.IGNORECASE | re.VERBOSE,
)
_HAS_LETTER = re.compile(r"\p{L}")
_LEADING_LABEL = re.compile(
    r"""^\s*(?:
        (?:chapter|part|unit|module|title|book|section|article|schedule|appendix)
            \s+(?:\d+|[ivxlcdm]+|[a-z])\b[.:\-–—]?
      | \[[\d:.\s\-–]+\]                   # [3:296.1 - 3:296.4]
      | \(?(?:\d+(?:\.\d+)*|[a-z]|[ivxlc]+)[.)]   # 3.4.  (a)  b.  iv)
      | \d+(?:\.\d+)+                        # 3.4.1
    )\s*""",
    re.IGNORECASE | re.VERBOSE,
)
_PLACEHOLDER = re.compile(r"^(?:reserved|omitted|deleted|repealed|intentionally left blank)\.?$",
                          re.IGNORECASE)
_BAD_ENDING = re.compile(r"[,;]$")


@dataclass
class Heading:
    level: int
    title: str
    page: int
    line_index: int                   # position of the heading line on its page


def body_font_size(pages: list[Page]) -> float:
    """Most common font size, weighted by number of characters."""
    sizes: Counter[float] = Counter()
    for page in pages:
        for line in page.lines:
            sizes[round(line.size)] += len(line.text)
    return float(sizes.most_common(1)[0][0]) if sizes else 0.0


def strip_numbering(text: str) -> str:
    """'3.5. Commercial General Liability' / 'E. Commercial ...' -> 'commercial general liability'."""
    previous = None
    text = text.strip()
    while previous != text:                   # labels can be stacked: "(a) [3:298] ..."
        previous = text
        text = _LEADING_LABEL.sub("", text, count=1).strip()
    return " ".join(text.rstrip(".:").lower().split())


def numbering_depth(text: str) -> int | None:
    """'3' -> 1, '3.4' -> 2, '3.4.1' -> 3, 'Chapter 2' -> 1, no numbering -> None."""
    m = _NUMBERING.match(text.strip())
    if not m:
        return None
    if m.group("dotted"):
        return m.group("dotted").count(".") + 1
    return 1


def _is_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters)


def _looks_like_heading_text(text: str) -> bool:
    text = text.strip()
    return (
        0 < len(text) <= MAX_HEADING_CHARS
        and len(text.split()) <= MAX_HEADING_WORDS
        and bool(_HAS_LETTER.search(text))
        and not _BAD_ENDING.search(text)
        and not is_page_number(text)
        and not _PLACEHOLDER.match(strip_numbering(text) + ".")
        and bool(strip_numbering(text))
        and not (text.endswith(".") and numbering_depth(text) is None and len(text) > 40)
    )


def detect_headings(pages: list[Page], max_levels: int = 3) -> list[Heading]:
    """Find heading lines using font size, bold, capitals and numbering."""
    body = body_font_size(pages)
    if body == 0:
        return []
    total_chars = sum(len(l.text) for p in pages for l in p.lines) or 1
    bold_share = sum(len(l.text) for p in pages for l in p.lines if l.bold) / total_chars
    bold_is_special = bold_share < 0.5        # if most text is bold, bold means nothing

    candidates: list[tuple[Page, int, TextLine, tuple]] = []
    for page in pages:
        for i, line in enumerate(page.lines):
            if not _looks_like_heading_text(line.text):
                continue
            bigger = line.size >= body * SIZE_RATIO
            bold = line.bold and bold_is_special and line.size >= body * 0.95
            caps = _is_caps(line.text) and line.size >= body * 0.95
            numbered = numbering_depth(line.text) is not None
            if bigger or (bold and (numbered or len(line.text) <= 80)) or (caps and numbered):
                style = (round(line.size), bold, caps)
                candidates.append((page, i, line, style))

    if not candidates:
        return []

    # Rank the distinct styles: bigger font first, then bold, then capitals.
    styles = sorted({c[3] for c in candidates}, key=lambda s: (-s[0], not s[1], not s[2]))
    style_level = {s: min(i + 1, max_levels) for i, s in enumerate(styles)}

    headings: list[Heading] = []
    for page, i, line, style in candidates:
        level = style_level[style]
        depth = numbering_depth(line.text)
        if len(styles) == 1 and depth:
            level = min(depth, max_levels)        # one style only: numbering decides
        prev = headings[-1] if headings else None
        # a heading wrapped over two lines -> join them
        if (prev and prev.page == page.page_number and prev.line_index == i - 1
                and prev.level == level and numbering_depth(line.text) is None):
            prev.title = f"{prev.title} {line.text.strip()}"
            prev.line_index = i
            continue
        headings.append(Heading(level=level, title=line.text.strip(),
                                page=page.page_number, line_index=i))
    return headings
