"""Keyword/regex scoring (free)."""

from __future__ import annotations

from collections import Counter

import regex as re

from lke.terms.patterns import find_terms

CONTENT_TYPES = ("CASE", "CONCEPT", "RULE", "EXAMPLE", "COMPARISON")

_CASE_WORDS = re.compile(
    r"\b(?:held|holds|holding|appellant|respondent|petitioner|plaintiff|defendant|"
    r"judgment|affirmed|reversed|remanded|overruled|dissent|the court (?:held|found|observed|"
    r"ruled|noted|concluded)|facts of the case|bench)\b", re.I)
_CONCEPT_WORDS = re.compile(
    r"\b(?:means|is defined as|refers to|definition|concept|doctrine|principle of|"
    r"the term|known as|in other words|purpose of)\b", re.I)
_RULE_WORDS = re.compile(
    r"\b(?:shall|must|may not|is required to|are required to|unless|provided that|except|"
    r"exempt(?:ion)?|prohibited|mandatory|requirement|condition precedent|entitled to|"
    r"liable (?:for|to)|exclusion|excludes|covers?)\b", re.I)
_EXAMPLE_WORDS = re.compile(
    r"\b(?:for example|for instance|e\.g\.|illustration|example:|suppose|hypothetical|"
    r"scenario|consider the following|assume that|let us say)\b", re.I)
_COMPARISON_WORDS = re.compile(
    r"\b(?:compare|comparison|whereas|in contrast|differs? from|distinguished from|"
    r"unlike|similarly|on the other hand|versus)\b", re.I)

_PROPRIETARY = re.compile(
    r"\b(?:practice pointers?|practice tips?|practical tips?|PRACTICE POINTER|in our view|"
    r"in our opinion|we recommend|we suggest|we believe|our firm|author'?s note|"
    r"editor'?s note|cautions?:|strategy:|checklist|form \d+)\b", re.I)

_SKIP_TITLES = re.compile(
    r"^\s*(?:table of contents|contents|index|bibliography|table of cases|table of statutes|"
    r"acknowledg(?:e)?ments?|about the authors?|preface|foreword|copyright|abbreviations)\s*$",
    re.I)
_DOT_LEADER = re.compile(r"(?:\.{3,}|…|\s{3,})\s*\d+\s*$", re.M)

MIN_TOKENS = 40


def _per_1000(count: int, tokens: int) -> float:
    return round(count * 1000 / max(tokens, 1), 2)


def score_text(text: str, token_estimate: int, has_tables: bool = False) -> dict[str, float]:
    terms = Counter(t.kind for t in find_terms(text))
    raw = {
        "CASE": 3 * terms["case_name"] + 2 * terms["citation"] + terms["court"]
                + len(_CASE_WORDS.findall(text)),
        "CONCEPT": 2 * terms["defined_term"] + len(_CONCEPT_WORDS.findall(text)),
        "RULE": 2 * terms["provision"] + terms["statute"] + len(_RULE_WORDS.findall(text)),
        "EXAMPLE": 3 * len(_EXAMPLE_WORDS.findall(text)),
        "COMPARISON": len(_COMPARISON_WORDS.findall(text)) + (6 if has_tables else 0),
    }
    return {k: _per_1000(v, token_estimate) for k, v in raw.items()}


def skip_reason(title: str, text: str, token_estimate: int) -> str | None:
    """Reasons a section is not worth sending to the LLM."""
    if token_estimate < MIN_TOKENS:
        return "too short"
    if _SKIP_TITLES.match(title or ""):
        return f"front/back matter ({title.strip()})"
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("[[p.")]
    if lines and sum(1 for l in lines if _DOT_LEADER.search(l)) / len(lines) > 0.5:
        return "table of contents"
    return None


def proprietary_signals(text: str) -> list[str]:
    return sorted({m.group(0).strip().lower() for m in _PROPRIETARY.finditer(text)})
