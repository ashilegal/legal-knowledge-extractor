"""No invented citations, no synonym swaps."""

from __future__ import annotations

import regex as re

from lke.extract.fact_extractor import ExtractedItem
from lke.models import AnyRecord
from lke.terms import find_terms, key

_LOOSE = re.compile(r"[^\p{L}\p{N}§]+")


def _loose(text: str) -> str:
    return _LOOSE.sub("", text.lower())


def _record_identifiers(record: AnyRecord) -> list[tuple[str, str]]:
    f = record.fields
    out: list[tuple[str, str]] = []
    if record.record_type == "CASE":
        out.append(("case_name", f.case_name))
        if f.citation:
            out += [("citation", c.strip()) for c in re.split(r"[;,]", f.citation) if c.strip()]
        if f.court:
            out.append(("court", f.court))
        out += [("party", p.name) for p in f.parties]
    for law in getattr(f, "laws", []) + getattr(f, "provisions", []):
        if law.statute:
            out.append(("statute", law.statute))
        if law.provision:
            out.append(("provision", law.provision))
    out += [("case_name", r.name) for r in f.related if r.type == "CASE"]
    return out


_SECTION_SPLIT = re.compile(r"^(.*?§+)\s*([\d.]+[A-Za-z]*)")


def _in_section_list(value: str, source_text: str) -> bool:
    """'42 USC § 1981' is supported by a source that says '42 USC §§ 1981, 1983 and 1985'."""
    m = _SECTION_SPLIT.match(value.strip())
    if not m:
        return False
    code, number = _loose(m.group(1).rstrip("§ ")), m.group(2)
    loose = source_text.lower()
    for hit in re.finditer(re.escape(number), loose):
        window = _loose(loose[max(0, hit.start() - 80):hit.start()])
        if code and code in window:
            return True
    return False


def check_terms(record: AnyRecord, source_text: str, item: ExtractedItem | None
                ) -> tuple[list[str], list[str]]:
    """Errors: identifiers that do not occur in the source (possibly invented).
    Warnings: protected terms from the notes that the record no longer uses."""
    errors: list[str] = []
    warnings: list[str] = []
    source_keys = {key(t.kind, t.text) for t in find_terms(source_text)}
    loose_source = _loose(source_text)
    for kind, value in _record_identifiers(record):
        if not value:
            continue
        lookup_kind = kind if kind != "party" else "case_name"
        if key(lookup_kind, value) in source_keys or _loose(value) in loose_source:
            continue
        if kind in ("provision", "statute") and _in_section_list(value, source_text):
            continue
        errors.append(f"{kind} not found in source: '{value}'")

    if item is not None:
        record_text = _loose(" ".join(getattr(s, "text", "") for s in record.statements())
                             + " " + record.model_dump_json())
        for ident in item.identifiers:
            if ident.kind == "defined_term" and _loose(ident.value) not in record_text:
                warnings.append(f"defined term not used in record: '{ident.value}'")
    return errors, warnings
