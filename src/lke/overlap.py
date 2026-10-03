"""Shared-wording measurement between generated text and the source section.

What is measured (ordinary wording only):
- longest run of consecutive words copied from the source
- share of the record's 8-word sequences that also occur in the source
- best similarity between any record sentence and any source sentence

What is NOT counted as copying: case names, citations, courts, statutes, section numbers,
dates, defined terms, legal terms of art and the identifiers of the record itself. They are
masked on both sides so they can never form part of a "copied" run.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import regex as re
from rapidfuzz import fuzz

from lke.models import AnyRecord
from lke.models.records import ComparisonItem
from lke.terms import find_terms
from lke.terms.legal_terms import DEFAULT_PATTERN, term_pattern

NGRAM = 8
MIN_SENTENCE_WORDS = 8
_WORD = re.compile(r"[\p{L}\p{N}]+(?:['’][\p{L}]+)?")
_MARKER = re.compile(r"\[\[p\. \d+\]\]|\[TABLE")
_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+|\n{2,}")


def _spans(text: str, terms: re.Pattern) -> list[tuple[int, int]]:
    spans = [(t.start, t.end) for t in find_terms(text)]
    spans += [(m.start(), m.end()) for m in terms.finditer(text)]
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    return merged


def _tokens(text: str, mask_token: str, terms: re.Pattern = DEFAULT_PATTERN) -> list[str]:
    """Lower-case ordinary words; every protected term becomes one token that never matches
    the other side, so it breaks a run instead of extending it."""
    text = _MARKER.sub(" ", text)
    out: list[str] = []
    pos = 0
    for start, end in _spans(text, terms) + [(len(text), len(text))]:
        out += [w.lower() for w in _WORD.findall(text[pos:start])]
        if start < end:
            out.append(mask_token)
        pos = end
    return out


def _plain(words: list[str]) -> str:
    return " ".join(w for w in words if not w.startswith("\x00"))


@dataclass
class OverlapResult:
    max_run: int = 0
    ratio: float = 0.0
    sentence_similarity: float = 0.0                       # 0..1, best record/source pair
    copied_sentence: str | None = None
    phrases: list[str] = field(default_factory=list)      # copied runs, record side

    @property
    def score(self) -> float:
        """One similarity number 0..1 (higher = closer to the source wording)."""
        return round(max(self.ratio, self.sentence_similarity), 2)

    def ok(self, max_run: int, max_ratio: float, max_sentence: float = 0.85) -> bool:
        return (self.max_run < max_run and self.ratio <= max_ratio
                and self.sentence_similarity < max_sentence)


class SourceIndex:
    """Positions of every ordinary word of the source and its sentences, built once."""

    def __init__(self, source_text: str, extra_terms: list[str] | None = None):
        self.terms = term_pattern(extra_terms) if extra_terms else DEFAULT_PATTERN
        self.tokens = _tokens(source_text, "\x00src", self.terms)
        self.positions: dict[str, list[int]] = defaultdict(list)
        for i, tok in enumerate(self.tokens):
            self.positions[tok].append(i)
        self.ngrams = {tuple(self.tokens[i:i + NGRAM])
                       for i in range(len(self.tokens) - NGRAM + 1)}
        self.sentences: list[str] = []
        for raw in _SENTENCE_END.split(_MARKER.sub(" ", source_text)):
            words = _tokens(raw, "\x00src", self.terms)
            if len(words) >= MIN_SENTENCE_WORDS:
                self.sentences.append(_plain(words))

    def tokens_of(self, text: str) -> list[str]:
        return _tokens(text, "\x00rec", self.terms)

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

    def best_sentence(self, words: list[str]) -> tuple[float, str | None]:
        """Most similar source sentence to this record sentence (0..1)."""
        if len(words) < MIN_SENTENCE_WORDS:
            return 0.0, None
        plain = _plain(words)
        best, which = 0.0, None
        for sentence in self.sentences:
            score = fuzz.ratio(plain, sentence) / 100
            if score > best:
                best, which = score, sentence
        return best, which


def _record_texts(record: AnyRecord) -> list[str]:
    texts = []
    for st in record.statements():
        if isinstance(st, ComparisonItem):
            texts.append(f"{st.subject} {st.attribute} {st.value}")
        else:
            texts += [s for s in _SENTENCE_END.split(st.text) if s.strip()]
    return texts


def check_overlap(record: AnyRecord, index: SourceIndex, report_from: int = 6) -> OverlapResult:
    result = OverlapResult()
    total = shared = 0
    for text in _record_texts(record):
        words = index.tokens_of(text)
        grams = [tuple(words[i:i + NGRAM]) for i in range(len(words) - NGRAM + 1)]
        total += len(grams)
        shared += sum(1 for g in grams if g in index.ngrams)
        similarity, sentence = index.best_sentence(words)
        if similarity > result.sentence_similarity:
            result.sentence_similarity = round(similarity, 3)
            result.copied_sentence = text
        runs = index.longest_runs(words)
        if not runs:
            continue
        length, end = max(runs)
        result.max_run = max(result.max_run, length)
        if length >= report_from:
            phrase = " ".join(w for w in words[end - length + 1:end + 1]
                              if not w.startswith("\x00"))
            result.phrases.append(phrase)
    result.ratio = round(shared / total, 3) if total else 0.0
    return result


# Small words that carry the source's sentence shape but little meaning.
STOPWORDS = frozenset("""
a an the of to in on at by for from with into onto upon as that which who whom whose
this these those is are was were be been being has have had do does did will would shall
should may might can could must it its their there here such any each than then so
and or but if when where while because although though also only even very
he she him her his hers they them theirs we us our you your i me my
""".split())


def telegraphic(note: str) -> str:
    """Reduce a note to its content words, so its sentence shape can't be carried over:
    'the employee had previously filed an arbitration claim' ->
    'employee previously filed arbitration claim'. Identifiers and numbers are kept."""
    words = note.split()
    kept = [w for w in words if w.strip(",.;:()").lower() not in STOPWORDS]
    return " ".join(kept) if len(kept) >= 2 else note


def longest_run(text: str, index: SourceIndex) -> int:
    runs = index.longest_runs(index.tokens_of(text))
    return max((length for length, _ in runs), default=0)
