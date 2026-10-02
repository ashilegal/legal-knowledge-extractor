"""'S. 25F' = 'Section 25F' normalisation."""

from __future__ import annotations

import regex as re

_SPACES = re.compile(r"\s+")
_PROVISION_WORDS = [
    (re.compile(r"^(?:Sections?|Secs?\.?|S\.|s\.|ss\.)\s*", re.I), "Section "),
    (re.compile(r"^(?:Articles?|Arts?\.)\s*", re.I), "Article "),
    (re.compile(r"^(?:Regulations?|Regs?\.)\s*", re.I), "Regulation "),
    (re.compile(r"^(?:Rules?)\s*", re.I), "Rule "),
    (re.compile(r"^(?:Clauses?)\s*", re.I), "Clause "),
    (re.compile(r"^(?:Paragraph|Para\.?)\s*", re.I), "Paragraph "),
]
_VERSUS = re.compile(r"\s+(?:v\.?|vs\.?|versus)\s+", re.I)
_COMPANY = [
    (re.compile(r"\blimited\b", re.I), "ltd"),
    (re.compile(r"\bincorporated\b", re.I), "inc"),
    (re.compile(r"\bcompany\b", re.I), "co"),
    (re.compile(r"\bcorporation\b", re.I), "corp"),
    (re.compile(r"\bprivate\b", re.I), "pvt"),
]
_NON_ALNUM = re.compile(r"[^\p{L}\p{N}§]+")


def normalise(kind: str, text: str) -> str:
    """Display form: one consistent spelling for the same identifier."""
    text = _SPACES.sub(" ", text).strip(" ,;:")
    if kind == "provision":
        for pattern, word in _PROVISION_WORDS:
            if pattern.match(text):
                rest = pattern.sub("", text, count=1)
                rest = re.sub(r"^(\d+)\s*[-–]?\s*([A-Z]{1,3})\b", r"\1\2", rest)  # 25-F -> 25F
                return word + rest
        return re.sub(r"§\s*", "§ ", text)
    if kind == "case_name":
        return _VERSUS.sub(" v. ", text)
    return text


def key(kind: str, text: str) -> str:
    """Matching key: ignores case, punctuation, spacing and common abbreviations."""
    value = normalise(kind, text).lower()
    if kind in ("case_name", "statute", "court"):
        for pattern, short in _COMPANY:
            value = pattern.sub(short, value)
        value = re.sub(r"^the\s+", "", value)
    return _NON_ALNUM.sub("", value)


def same(kind: str, a: str, b: str) -> bool:
    return key(kind, a) == key(kind, b)
