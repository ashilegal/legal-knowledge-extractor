"""List of terms that must stay exact."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from lke.terms.glossary import key, normalise
from lke.terms.patterns import find_terms

# Defined terms and statutes are only treated as protected when they look important.
MIN_MENTIONS = {"defined_term": 1, "statute": 1}


@dataclass
class ProtectedTerms:
    """Identifiers found in a piece of source text, grouped by kind."""

    by_kind: dict[str, list[str]] = field(default_factory=dict)
    keys: set[str] = field(default_factory=set)

    def all(self) -> list[str]:
        return [t for terms in self.by_kind.values() for t in terms]

    def contains(self, kind: str, text: str) -> bool:
        return key(kind, text) in self.keys

    def as_prompt_list(self, limit: int = 120) -> str:
        lines = []
        for kind, terms in self.by_kind.items():
            if terms:
                lines.append(f"- {kind}: " + "; ".join(terms[:40]))
        return "\n".join(lines[:limit]) or "- (none detected)"

    def to_dict(self) -> dict[str, list[str]]:
        return self.by_kind


def protected_terms(text: str) -> ProtectedTerms:
    counts: Counter[tuple[str, str]] = Counter()
    display: dict[tuple[str, str], str] = {}
    for term in find_terms(text):
        k = (term.kind, key(term.kind, term.text))
        counts[k] += 1
        display.setdefault(k, normalise(term.kind, term.text))
    result = ProtectedTerms()
    for (kind, k), n in counts.items():
        if n < MIN_MENTIONS.get(kind, 1) or not k:
            continue
        result.by_kind.setdefault(kind, []).append(display[(kind, k)])
        result.keys.add(k)
    return result
