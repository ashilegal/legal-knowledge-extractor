"""Build Topic > Subtopic > Section tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import regex as re
from rapidfuzz import fuzz

from lke.models import Page, make_id
from lke.structure.headings import Heading, detect_headings, strip_numbering
from lke.structure.toc import TocEntry, read_toc

MIN_TOC_ENTRIES = 3


@dataclass
class TopicNode:
    node_id: str
    title: str
    level: int
    page: int
    line_index: int
    children: list["TopicNode"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id, "title": self.title, "level": self.level,
            "page": self.page, "children": [c.to_dict() for c in self.children],
        }


def clean_title(name: str) -> str:
    """'3.4 Employee Benefits Liability EBL Insurance_1' -> readable document title."""
    name = re.sub(r"[_]+", " ", name)
    name = re.sub(r"\s+\d+$", "", name.strip())
    return " ".join(name.split())


def toc_to_headings(toc: list[TocEntry], pages: list[Page], max_levels: int) -> list[Heading]:
    """Place each bookmark on the exact line of its page (fuzzy title match)."""
    by_number = {p.page_number: p for p in pages}
    headings = []
    for entry in toc:
        page = by_number.get(entry.page)
        line_index = 0
        if page and page.lines:
            scores = [fuzz.partial_ratio(entry.title.lower(), l.text.lower()) for l in page.lines]
            best = max(range(len(scores)), key=scores.__getitem__)
            if scores[best] >= 85:
                line_index = best
        headings.append(Heading(level=min(entry.level, max_levels), title=entry.title,
                                page=entry.page, line_index=line_index))
    return headings


def normalise_levels(headings: list[Heading]) -> list[Heading]:
    """Make the highest level present become level 1, and never skip levels downward."""
    if not headings:
        return headings
    shift = min(h.level for h in headings) - 1
    previous = 0
    for h in headings:
        h.level = min(h.level - shift, previous + 1)
        previous = h.level
    return headings


def find_headings(
    pages: list[Page], pdf_path: Path | None, max_levels: int = 3
) -> tuple[str, list[Heading]]:
    """Returns (source, headings): source is 'toc', 'headings' or 'none'."""
    toc = read_toc(pdf_path) if pdf_path else []
    if len(toc) >= MIN_TOC_ENTRIES:
        return "toc", normalise_levels(toc_to_headings(toc, pages, max_levels))
    detected = detect_headings(pages, max_levels)
    if detected:
        return "headings", normalise_levels(detected)
    return "none", []


def build_tree(doc_id: str, doc_title: str, headings: list[Heading]) -> TopicNode:
    """Root = the document; children follow heading levels."""
    root = TopicNode(make_id("node", doc_id, "root"), doc_title, 0, 1, 0)
    stack = [root]
    for n, h in enumerate(headings):
        node = TopicNode(make_id("node", doc_id, n, h.title), h.title, h.level, h.page,
                         h.line_index)
        while stack[-1].level >= h.level:
            stack.pop()
        stack[-1].children.append(node)
        stack.append(node)
    return root


def topic_path_for(headings: list[Heading], index: int) -> list[str]:
    """Breadcrumb of heading titles leading to headings[index]: [topic, subtopic, ...]."""
    path: list[str] = []
    level = headings[index].level + 1
    for h in reversed(headings[: index + 1]):
        if h.level < level:
            path.insert(0, h.title)
            level = h.level
    # "3.5 CGL Insurance" > "E. CGL Insurance" is one level, not two
    deduped: list[str] = []
    for title in path:
        if deduped and strip_numbering(deduped[-1]) == strip_numbering(title):
            continue
        deduped.append(title)
    return deduped
