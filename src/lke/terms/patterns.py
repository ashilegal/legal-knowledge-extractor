"""Regex: case names, citations, sections, courts, dates."""

from __future__ import annotations

from dataclasses import dataclass

import regex as re

# ---------- building blocks ----------

_NAME_WORD = r"[A-Z][\w'’.&\-]*"
_LINK_WORD = r"(?:of|the|and|for|de|du|la|del|von|van|ex|rel\.|&)"
_SUFFIX = r"(?:,\s+(?:Inc|Ltd|Co|Corp|LLC|LLP|L\.P|N\.A|P\.C|Pvt|Plc|PLC|S\.A)\.?)"
_PARTY = rf"{_NAME_WORD}(?:\s+(?:{_NAME_WORD}|{_LINK_WORD})){{0,7}}{_SUFFIX}?"
_MONTHS = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
           r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")

# Words that often precede a case name but are not part of it.
LEADING_NOISE = re.compile(
    r"^(?:(?:In|See|See also|Compare|Cf\.?|Also|But|And|Accord|Contra|E\.g\.,?|Per|Following|"
    r"Under|After|Before|Since|While|Although|When|Thus|Hence|Therefore|The|This|That|"
    r"Court|Courts|Held|Holding|Case|Decision|Judgment|Following)\s+)+"
)

CASE_NAME = re.compile(
    rf"(?<![\w\-–.'’])(?:(?:In\s+re|Ex\s+parte|Re)\s+{_PARTY}"
    rf"|{_PARTY}\s+(?:v\.?|vs\.?|versus)\s+{_PARTY})"
)

CITATION = re.compile(
    r"""(?:
      AIR\s+\d{4}\s+[A-Z][A-Za-z.]{1,12}\s+\d+                         # AIR 1978 SC 597
    | \(\d{4}\)\s+\d+\s+SCC(?:\s+\(L&S\))?\s+\d+                      # (1978) 2 SCC 213
    | \[\d{4}\]\s+\d+\s+S\.?C\.?R\.?\s+\d+                             # [1978] 3 SCR 207
    | \d{4}\s+SCC\s+OnLine\s+[A-Z][A-Za-z]*\s+\d+                      # 2020 SCC OnLine SC 1
    | \[\d{4}\]\s+(?:UKSC|UKHL|UKPC|EWCA\s+(?:Civ|Crim)|EWHC|CSIH|NICA)\s+\d+(?:\s*\([A-Za-z]+\))?
    | \[\d{4}\]\s+\d*\s*(?:AC|QB|KB|Ch|WLR|All\s?ER|ICR|IRLR|Lloyd's\s+Rep)\s+\d+
    | \d+\s+(?:U\.?\s?S\.?|S\.?\s?Ct\.?|L\.?\s?Ed\.?(?:\s?2d)?|F\.?\s?(?:2d|3d|4th)|F[234]d|F4th
              |F\.?\s?Supp\.?(?:\s?[23]d)?|FS(?:upp)?[23]d|P\.?\s?[23]d|P[23]d
              |Cal\.?\s?(?:App\.?\s?)?(?:2d|3d|4th|5th)|C[A]?[2-5](?:d|th)|CA[2-5](?:d|th)
              |Cal\.?\s?Rptr\.?(?:\s?[23]d)?|CR[23]d|N\.?E\.?[23]d|N\.?W\.?[23]d|S\.?W\.?[23]d
              |A\.?[23]d|So\.?\s?[23]d)\s+\d+                           # 109 F3d 642, 25 C4th 1
    | \(\d{4}\)\s+\d+\s+[A-Z][A-Za-z.]{1,10}\s+\d+                     # (2001) 25 C4th 1 style
    )""",
    re.VERBOSE,
)

PROVISION = re.compile(
    r"""(?:
      \d+\s+U\.?S\.?C\.?\s+§+\s*[\d.]+[A-Za-z]*(?:\([0-9a-zA-Z]+\))*  # 42 U.S.C. § 1983
    | \d+\s+C\.?F\.?R\.?\s+§*\s*[\d.]+                                # 29 CFR 1604.11
    | \b(?:[A-Z][a-z]{1,6}\.\s?){1,3}C\.\s+§+\s*[\d.]+[A-Za-z]*(?:\([0-9a-zA-Z]+\))*   # Ins.C. § 533
    | \b[A-Z]{2,6}\s+§+\s*[\d.]+[A-Za-z]*(?:\([0-9a-zA-Z]+\))*        # CCP § 425.16
    | Order\s+[IVXLC]+\s+Rule\s+\d+[A-Z]*                             # Order VII Rule 11
    | (?:Sections?|Secs?\.?|S\.|s\.|ss\.|§§?|Articles?|Arts?\.|Rules?|Regulations?|Regs?\.
         |Clauses?|Paragraph|Para\.?|Schedule)
      \s*\d+[A-Z]{0,3}(?:[-–]\d*[A-Z]{1,3})?(?:\s*\([0-9a-zA-Z]{1,4}\))*
    )""",
    re.VERBOSE,
)

STATUTE = re.compile(
    r"(?<![\w\-–.'’])(?:The\s+)?(?:[A-Z][\w'’\-]*|\([A-Z]+\))"
    r"(?:\s+(?:[A-Z][\w'’\-]*|of|and|for|the|on|to|in|&|\([A-Z]+\))){0,10}"
    r"\s+(?:Act|Code|Rules|Regulations|Ordinance|Constitution|Directive)"
    r"(?:,?\s+(?:of\s+)?\d{4})?"
    r"|\bConstitution\s+of\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*"
    r"|\bTitle\s+[IVXLC]+\s+of\s+the\s+Civil\s+Rights\s+Act(?:\s+of\s+\d{4})?"
)

COURT = re.compile(
    r"""\b(?:
      Supreme\s+Court(?:\s+of\s+(?:India|the\s+United\s+States|the\s+United\s+Kingdom|[A-Z][a-z]+))?
    | (?:[A-Z][a-z]+\s+)?High\s+Court(?:\s+of\s+[A-Z][a-z]+(?:\s+(?:and\s+)?[A-Z][a-z]+)*)?
    | Court\s+of\s+Appeals?(?:\s+for\s+the\s+[\w\s]+?\s+Circuit)?
    | House\s+of\s+Lords | Privy\s+Council
    | (?:Employment\s+Appeal|Employment|Industrial|Income\s+Tax\s+Appellate|Central\s+Administrative)
        \s+Tribunal
    | National\s+Company\s+Law\s+(?:Appellate\s+)?Tribunal
    | Labour\s+Court | District\s+Court | Circuit\s+Court | Court\s+of\s+Justice\s+of\s+the\s+European\s+Union
    | \d+(?:st|nd|rd|th)\s+Cir\.
    | Cal\.\s+Supreme\s+Court
    )""",
    re.VERBOSE,
)

DATE = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\.?,?\s+\d{{4}}"
    rf"|\b{_MONTHS}\.?\s+\d{{1,2}},\s+\d{{4}}"
    r"|\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b"
)

DEFINED_TERM = re.compile(
    r"[\"“‘']([^\"”’'\n]{2,60})[\"”’']\s*(?::|means|shall\s+mean|includes|refers\s+to|is\s+defined\s+as)"
)

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("citation", CITATION),
    ("provision", PROVISION),
    ("case_name", CASE_NAME),
    ("court", COURT),
    ("statute", STATUTE),
    ("date", DATE),
]


@dataclass(frozen=True)
class Term:
    kind: str          # case_name, citation, provision, statute, court, date, defined_term
    text: str          # exactly as written in the source
    start: int
    end: int


def _clean_case_name(text: str) -> str:
    return LEADING_NOISE.sub("", text).strip(" ,;:")


def find_terms(text: str) -> list[Term]:
    """All identifiers in the text. Overlaps are resolved in favour of the longer match."""
    found: list[Term] = []
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(text):
            value = m.group(0).strip(" ,;:")
            if kind in ("provision", "citation", "date"):
                value = value.rstrip(".")
            start = m.start()
            if kind == "case_name":
                cleaned = _clean_case_name(value)
                start += value.find(cleaned) if cleaned else 0
                value = cleaned
                if " v" not in value and not value.lower().startswith(("in re", "ex parte", "re ")):
                    continue
            if len(value) < 3:
                continue
            if kind == "statute" and len(re.sub(r"^The\s+", "", value).split()) < 2:
                continue                                  # "The Act", "Code" alone

            found.append(Term(kind, value, start, start + len(value)))
    for m in DEFINED_TERM.finditer(text):
        found.append(Term("defined_term", m.group(1).strip(), m.start(1), m.end(1)))

    # keep the longest match where two overlap (e.g. "Section 25F" inside a citation)
    found.sort(key=lambda t: (t.start, -(t.end - t.start)))
    result: list[Term] = []
    for term in found:
        if result and term.start < result[-1].end and term.kind != "defined_term":
            continue
        result.append(term)
    return result
