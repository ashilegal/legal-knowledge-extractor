"""Required fields, correct types."""

from __future__ import annotations

from lke.models import AnyRecord

MAX_STATEMENT_CHARS = 700


def check_schema(record: AnyRecord) -> list[str]:
    """Pydantic already enforced types; here: is the record useful and complete enough?"""
    errors: list[str] = []
    f = record.fields
    t = record.record_type
    if t == "CASE":
        if not (f.decision or f.principles or f.material_facts or f.legal_issues):
            errors.append("case has no facts, issues, decision or principles")
    elif t == "CONCEPT":
        if not (f.definition or f.key_points):
            errors.append("concept has neither a definition nor key points")
    elif t == "RULE":
        if not (f.requirements or f.conditions or f.exceptions):
            errors.append("rule has no requirements, conditions or exceptions")
    elif t == "COMPARISON":
        if not f.items and not f.key_differences:
            errors.append("comparison has no items")
    for st in record.statements():
        text = getattr(st, "text", None)
        if text is not None and len(text) > MAX_STATEMENT_CHARS:
            errors.append(f"statement too long ({len(text)} chars)")
    return errors
