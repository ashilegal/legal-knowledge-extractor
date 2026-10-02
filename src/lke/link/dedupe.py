"""Merge records split across sections."""

from __future__ import annotations

from rapidfuzz import fuzz

from lke.models import AnyRecord
from lke.models.records import ComparisonItem, Statement

SIMILAR = 90          # statements at least this similar are treated as the same point


def _merge_statements(old: list[Statement], new: list[Statement]) -> list[Statement]:
    merged = list(old)
    for st in new:
        twin = next((o for o in merged
                     if fuzz.token_set_ratio(o.text.lower(), st.text.lower()) >= SIMILAR), None)
        if twin is None:
            merged.append(st)
        else:                                  # same point: keep both sources of evidence
            twin.evidence = list(dict.fromkeys(twin.evidence + st.evidence))
    return merged


def merge_records(existing: AnyRecord, new: AnyRecord) -> AnyRecord:
    """Combine two records about the same case/concept/rule (from any documents)."""
    if existing.record_type != new.record_type:
        raise ValueError("cannot merge records of different types")
    merged = existing.model_copy(deep=True)
    known = {e.id for e in merged.evidence}
    merged.evidence += [e for e in new.evidence if e.id not in known]

    a, b = merged.fields, new.fields
    for name in type(a).model_fields:
        old_value, new_value = getattr(a, name), getattr(b, name)
        if isinstance(old_value, list) and old_value and isinstance(old_value[0], Statement) \
                or (isinstance(new_value, list) and new_value
                    and isinstance(new_value[0], Statement)):
            setattr(a, name, _merge_statements(old_value, new_value))
        elif isinstance(old_value, list):
            if new_value and isinstance(new_value[0], ComparisonItem):
                setattr(a, name, old_value + new_value)
            else:
                seen = [x.model_dump_json() if hasattr(x, "model_dump_json") else x
                        for x in old_value]
                extra = [x for x in new_value
                         if (x.model_dump_json() if hasattr(x, "model_dump_json") else x)
                         not in seen]
                setattr(a, name, old_value + extra)
        elif old_value in (None, "") and new_value not in (None, ""):
            setattr(a, name, new_value)
        elif name == "citation" and new_value and new_value not in (old_value or ""):
            setattr(a, name, f"{old_value}; {new_value}")

    merged.flags.proprietary = existing.flags.proprietary or new.flags.proprietary
    merged.flags.low_ocr_confidence = (existing.flags.low_ocr_confidence
                                       or new.flags.low_ocr_confidence)
    merged.flags.reasons = list(dict.fromkeys(existing.flags.reasons + new.flags.reasons))
    if merged.topic is None:
        merged.topic, merged.subtopic = new.topic, new.subtopic
    return merged
