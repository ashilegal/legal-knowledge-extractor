"""Detects copied wording (n-gram, longest run)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import regex as re

from lke.models import AnyRecord
from lke.models.records import ComparisonItem
from lke.terms import find_terms

NGRAM = 8
_WORD = re.compile(r"[\p{L}\p{N}]+(?:['’][\p{L}]+)?")
_MARKER = re.compile(r"\[\[p\. \d+\]\]|\[TABLE")


def _tokens(text: str, mask_token: str) -> list[str]:
    """Lower-case words; legal identifiers become a token that never matches the other side,
    so case names and section numbers don't count as copying."""
    text = _MARKER.sub(" ", text)
    spans = [(t.start, t.end) for t in find_terms(text)]
    out: list[str] = []
    pos = 0
    for start, end in spans + [(len(text), len(text))]:
        out += [w.lower() for w in _WORD.findall(text[pos:start])]
        if start < end:
            out.append(mask_token)
        pos = end
    return out


@dataclass
class OverlapResult:
    max_run: int = 0
    ratio: float = 0.0
    phrases: list[str] = field(default_factory=list)      # copied runs, record side

    def ok(self, max_run: int, max_ratio: float) -> bool:
        return self.max_run < max_run and self.ratio <= max_ratio


class SourceIndex:
    """Positions of every word of the source, built once per section."""

    def __init__(self, source_text: str):
        self.tokens = _tokens(source_text, "\x00src")
        self.positions: dict[str, list[int]] = defaultdict(list)
        for i, tok in enumerate(self.tokens):
            self.positions[tok].append(i)
        self.ngrams = {tuple(self.tokens[i:i + NGRAM])
                       for i in range(len(self.tokens) - NGRAM + 1)}

    def longest_runs(self, words: list[str]) -> list[tuple[int, int]]:
        """(length, end index in words) of the longest shared run ending at each word."""
        prev: dict[int, int] = {}
        best: list[tuple[int, int]] = []
        for i, w in enumerate(words):
            cur: dict[int, int] = {}
            for j in self.positions.get(w, ()):
                cur[j] = prev.get(j - 1, 0) + 1
            if cur:
                best.append((max(cur.values()), i))
            prev = cur
        return best


def check_overlap(record: AnyRecord, index: SourceIndex, report_from: int = 6) -> OverlapResult:
    texts = []
    for st in record.statements():
        texts.append(f"{st.subject} {st.attribute} {st.value}"
                     if isinstance(st, ComparisonItem) else st.text)
    result = OverlapResult()
    total = shared = 0
    for text in texts:
        words = _tokens(text, "\x00rec")
        grams = [tuple(words[i:i + NGRAM]) for i in range(len(words) - NGRAM + 1)]
        total += len(grams)
        shared += sum(1 for g in grams if g in index.ngrams)
        runs = index.longest_runs(words)
        if not runs:
            continue
        length, end = max(runs)
        result.max_run = max(result.max_run, length)
        if length >= report_from:
            phrase = " ".join(w for w in words[end - length + 1:end + 1] if w != "\x00rec")
            result.phrases.append(phrase)
    result.ratio = round(shared / total, 3) if total else 0.0
    return result
