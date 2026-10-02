"""Every fact points to a real page/span."""

from __future__ import annotations

from lke.models import AnyRecord, Section
from lke.models.records import Basis, ComparisonItem


def check_grounding(record: AnyRecord, section: Section) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    for ev in record.evidence:
        if ev.doc_id != section.doc_id:
            errors.append(f"evidence {ev.id} points to another document")
        if any(p < section.page_start or p > section.page_end for p in ev.pages):
            errors.append(f"evidence {ev.id} cites pages outside {section.page_start}-"
                          f"{section.page_end}")
    for st in record.statements():
        label = (f"{st.subject}/{st.attribute}" if isinstance(st, ComparisonItem)
                 else st.text[:60])
        if not st.evidence:
            if st.basis == Basis.SOURCE:
                errors.append(f"source statement without supporting notes: '{label}'")
            else:
                warnings.append(f"interpretation without supporting notes: '{label}'")
    return errors, warnings
