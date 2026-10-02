"""Same case/statute across docs -> one entity."""

from __future__ import annotations

from lke.models import AnyRecord, make_id
from lke.store import Library
from lke.terms import key, normalise


def entity_id(entity_type: str, name: str) -> str:
    kind = {"CASE": "case_name", "STATUTE": "statute", "PROVISION": "provision",
            "COURT": "court"}.get(entity_type, "statute")
    return make_id("ent", entity_type, key(kind, name))


def resolve_entities(record: AnyRecord, lib: Library) -> None:
    """Register cases, courts, statutes and provisions; link LawRefs to their entity ids."""
    f = record.fields
    if record.record_type == "CASE":
        lib.upsert_entity(entity_id("CASE", f.case_name), "CASE",
                          normalise("case_name", f.case_name), f.case_name)
        if f.court:
            lib.upsert_entity(entity_id("COURT", f.court), "COURT", f.court, f.court)
    for law in getattr(f, "laws", []) + getattr(f, "provisions", []):
        if law.statute:
            lib.upsert_entity(entity_id("STATUTE", law.statute), "STATUTE", law.statute,
                              law.statute)
        if law.provision:
            name = f"{law.provision} {law.statute}".strip()
            eid = entity_id("PROVISION", name)
            lib.upsert_entity(eid, "PROVISION", name, law.provision)
            law.entity_id = eid
        elif law.statute:
            law.entity_id = entity_id("STATUTE", law.statute)
