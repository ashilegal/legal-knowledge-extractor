"""Split into sections of ~3-8k tokens with page ranges."""

from __future__ import annotations

from dataclasses import dataclass

from lke.config import SectioningConfig
from lke.ingest.cleaner import lines_to_text
from lke.models import Page, Section, TextLine, make_id
from lke.structure.headings import Heading
from lke.structure.topic_tree import topic_path_for

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def page_marker(page_number: int) -> str:
    return f"[[p. {page_number}]]"


def format_table(rows: list[list[str]]) -> str:
    return "\n".join("| " + " | ".join(cell or "" for cell in row) + " |" for row in rows)


@dataclass
class _Block:
    """Text of one heading's range, kept per page so markers can be added."""
    title: str
    topic_path: list[str]
    parts: list[tuple[int, list[str]]]            # (page_number, lines)
    tables: list[tuple[int, list[list[str]]]]

    def page_range(self) -> tuple[int, int]:
        pages = [p for p, _ in self.parts] or [t[0] for t in self.tables]
        return min(pages), max(pages)

    def render(self) -> str:
        grouped: list[tuple[int, list[str]]] = []
        for page_number, lines in self.parts:          # one marker per page run
            if grouped and grouped[-1][0] == page_number:
                grouped[-1][1].extend(lines)
            else:
                grouped.append((page_number, list(lines)))
        out: list[str] = []
        for page_number, lines in grouped:
            body = lines_to_text_from_strings(lines)
            if body:
                out.append(f"{page_marker(page_number)}\n{body}")
        for page_number, rows in self.tables:
            out.append(f"[TABLE {page_marker(page_number)}]\n{format_table(rows)}")
        return "\n\n".join(out).strip()


def lines_to_text_from_strings(lines: list[str]) -> str:
    return lines_to_text([TextLine(text=t) for t in lines])


def _blocks(pages: list[Page], headings: list[Heading], doc_title: str) -> list[_Block]:
    """Cut the document at every heading."""
    starts = {(h.page, h.line_index): i for i, h in enumerate(headings)}
    blocks: list[_Block] = [_Block(doc_title, [doc_title], [], [])]   # text before 1st heading
    for page in pages:
        current_lines: list[str] = []
        for i, line in enumerate(page.lines):
            if (page.page_number, i) in starts:
                if current_lines:
                    blocks[-1].parts.append((page.page_number, current_lines))
                    current_lines = []
                h_index = starts[(page.page_number, i)]
                h = headings[h_index]
                blocks.append(_Block(h.title, topic_path_for(headings, h_index), [], []))
                if line.text.strip() != h.title:      # TOC title not on this exact line
                    current_lines.append(line.text)
                continue
            current_lines.append(line.text)
        if current_lines:
            blocks[-1].parts.append((page.page_number, current_lines))
        for rows in page.tables:
            blocks[-1].tables.append((page.page_number, rows))
    return [b for b in blocks if b.parts or b.tables]


def _split_large(block: _Block, cfg: SectioningConfig) -> list[_Block]:
    """Split at line boundaries into parts of about target_tokens, with a small overlap."""
    if estimate_tokens(block.render()) <= cfg.max_tokens:
        return [block]
    target_chars = cfg.target_tokens * CHARS_PER_TOKEN
    overlap_chars = cfg.overlap_tokens * CHARS_PER_TOKEN
    flat = [(p, line) for p, lines in block.parts for line in lines]
    pieces: list[_Block] = []
    start = 0
    while start < len(flat):
        size, end = 0, start
        while end < len(flat) and (size < target_chars or end == start):
            size += len(flat[end][1]) + 1
            end += 1
        # prefer to stop at a paragraph-like boundary (line ending with . : ;)
        for back in range(end, max(start + 1, end - 40), -1):
            if flat[back - 1][1].rstrip().endswith((".", ":", ";")):
                end = back
                break
        chunk = flat[start:end]
        parts: list[tuple[int, list[str]]] = []
        for p, line in chunk:
            if parts and parts[-1][0] == p:
                parts[-1][1].append(line)
            else:
                parts.append((p, [line]))
        pieces.append(_Block(block.title, block.topic_path, parts, []))
        if end >= len(flat):
            break
        back_chars, new_start = 0, end
        while new_start > start + 1 and back_chars < overlap_chars:
            new_start -= 1
            back_chars += len(flat[new_start][1]) + 1
        start = new_start
    if block.tables:
        pieces[-1].tables = block.tables
    if len(pieces) > 1:
        for n, piece in enumerate(pieces, 1):
            piece.title = f"{block.title} (part {n}/{len(pieces)})"
    return pieces


def _merge_small(blocks: list[_Block], cfg: SectioningConfig) -> list[_Block]:
    """Join tiny sections with a neighbour so the LLM gets meaningful units.

    - a tiny block followed by one of its own sub-headings (e.g. a chapter's short
      introduction) or by anything when it is the front matter, is folded into
      the next block, which keeps its own topic path;
    - tiny neighbours under the same topic and subtopic are joined.
    """
    def tokens(b: _Block) -> int:
        return estimate_tokens(b.render())

    def heading_part(b: _Block) -> list[tuple[int, list[str]]]:
        page = b.parts[0][0] if b.parts else (b.tables[0][0] if b.tables else 1)
        return [(page, [b.title])]

    merged: list[_Block] = []
    for block in blocks:
        prev = merged[-1] if merged else None
        if prev is None:
            merged.append(block)
            continue
        is_ancestor = block.topic_path[: len(prev.topic_path)] == prev.topic_path
        is_front = len(merged) == 1 and prev.topic_path != block.topic_path[:1] and \
            len(prev.topic_path) == 1 and prev.title == prev.topic_path[0]
        fits = tokens(prev) + tokens(block) <= cfg.target_tokens
        if tokens(prev) < cfg.min_tokens and fits and (is_ancestor or is_front):
            block.parts = prev.parts + heading_part(block) + block.parts
            block.tables = prev.tables + block.tables
            merged[-1] = block
            continue
        if (prev.topic_path[:2] == block.topic_path[:2] and fits
                and (tokens(prev) < cfg.min_tokens or tokens(block) < cfg.min_tokens)):
            if block.title != prev.title:
                prev.parts.extend(heading_part(block))
            prev.parts.extend(block.parts)
            prev.tables.extend(block.tables)
            common = []
            for a, b in zip(prev.topic_path, block.topic_path):
                if a != b:
                    break
                common.append(a)
            prev.topic_path = common or prev.topic_path[:1]
            continue
        merged.append(block)
    return merged


def make_sections(
    doc_id: str, pages: list[Page], headings: list[Heading], doc_title: str,
    cfg: SectioningConfig,
) -> list[Section]:
    blocks = _merge_small(_blocks(pages, headings, doc_title), cfg)
    sections: list[Section] = []
    for block in blocks:
        for piece in _split_large(block, cfg):
            text = piece.render()
            if not text:
                continue
            start, end = piece.page_range()
            index = len(sections)
            sections.append(Section(
                section_id=make_id("sec", doc_id, index, piece.title),
                doc_id=doc_id,
                index=index,
                topic_path=piece.topic_path,
                title=piece.title,
                page_start=start,
                page_end=end,
                text=text,
                token_estimate=estimate_tokens(text),
                has_tables=bool(piece.tables),
            ))
    return sections
