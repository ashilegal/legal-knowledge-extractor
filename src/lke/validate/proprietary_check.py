"""Flags commentary / unique examples."""

from __future__ import annotations

import regex as re

from lke.models import AnyRecord

_FIRST_PERSON = re.compile(r"\b(?:[Ww]e|[Oo]ur|[Oo]urs)\b")    # not "US" or "I" (Title I)
_ADVICE = re.compile(r"\b(?:practice pointer|practice tip|counsel should|attorneys should|"
                     r"lawyers should|it is advisable|be sure to|consider (?:asking|adding))\b",
                     re.I)


def check_proprietary(record: AnyRecord) -> list[str]:
    """Reasons to treat the record as author commentary (empty list = none found)."""
    reasons = list(record.flags.reasons) if record.flags.proprietary else []
    text = " ".join(getattr(s, "text", "") for s in record.statements())
    if _FIRST_PERSON.search(text):
        reasons.append("first-person wording (author's voice)")
    if _ADVICE.search(text):
        reasons.append("practice advice")
    return list(dict.fromkeys(r for r in reasons if r))
