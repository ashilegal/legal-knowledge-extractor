"""Remove headers/footers/page numbers, fix hyphens."""

from __future__ import annotations

from collections import Counter

import regex as re

from lke.models import Page, TextLine

TOP_EDGE = 0.10                # top 10% of the page can hold a header
BOTTOM_EDGE = 0.90             # bottom 10% of the page can hold a footer
REPEAT_SHARE = 0.3             # appears on >= 30% of pages -> header/footer
MIN_PAGES_FOR_REPEATS = 2

_PAGE_NUMBER = re.compile(
    r"^\s*(?:page\s*)?[-–—(\[]?\s*(?:\d{1,5}|[ivxlcdm]{1,7})\s*[-–—)\]]?"
    r"(?:\s*(?:of|/)\s*\d{1,5})?\s*$",
    re.IGNORECASE,
)
_DIGITS = re.compile(r"\d+")
_HYPHEN_BREAK = re.compile(r"(\p{Ll})-\n(\p{Ll})")
_SPACES = re.compile(r"[ \t\xa0]+")    # spaces, tabs, non-breaking spaces
_BLANK_LINES = re.compile(r"\n{3,}")


def is_page_number(text: str) -> bool:
    return bool(_PAGE_NUMBER.match(text))


def _signature(text: str) -> str:
    """Normalise a line so 'Chapter 3 – page 12' and '... page 13' look the same."""
    return _DIGITS.sub("#", text.strip().lower())


def is_edge(line: TextLine) -> bool:
    return line.y < TOP_EDGE or line.y > BOTTOM_EDGE


def find_repeated_edges(pages: list[list[TextLine]]) -> set[str]:
    """Signatures of lines that repeat at the top/bottom of many pages."""
    if len(pages) < MIN_PAGES_FOR_REPEATS:
        return set()
    counts: Counter[str] = Counter()
    for lines in pages:
        counts.update({_signature(l.text) for l in lines if is_edge(l) and l.text.strip()})
    threshold = max(2, int(len(pages) * REPEAT_SHARE))
    return {sig for sig, n in counts.items() if n >= threshold}


def clean_lines(lines: list[TextLine], repeated: set[str]) -> list[TextLine]:
    """Drop page numbers and repeated headers/footers (only near the page edges)."""
    kept: list[TextLine] = []
    for line in lines:
        if is_edge(line) and (is_page_number(line.text) or _signature(line.text) in repeated):
            continue
        kept.append(line)
    return kept


def lines_to_text(lines: list[TextLine]) -> str:
    text = "\n".join(l.text for l in lines)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)          # "employ-\nment" -> "employment"
    text = _SPACES.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def clean_pages(pages: list[Page]) -> list[Page]:
    """Clean every page of one document. Page numbers and order are never changed."""
    repeated = find_repeated_edges([p.lines for p in pages])
    cleaned: list[Page] = []
    for page in pages:
        lines = clean_lines(page.lines, repeated)
        text = lines_to_text(lines)
        cleaned.append(page.model_copy(update={
            "lines": lines, "text": text, "char_count": len(text),
        }))
    return cleaned
