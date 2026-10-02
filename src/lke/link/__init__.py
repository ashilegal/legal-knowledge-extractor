"""Cross-document linking."""

from __future__ import annotations

from lke.link.dedupe import merge_records
from lke.link.entity_resolver import entity_id, resolve_entities
from lke.link.relations import build_relations, save_relations, save_topics
from lke.models import AnyRecord
from lke.store import Library


def store_record(record: AnyRecord, lib: Library) -> AnyRecord:
    """Merge with any existing record of the same identity, then save with its links."""
    existing = lib.get_record(record.record_id)
    if existing is not None:
        record = merge_records(existing, record)
    resolve_entities(record, lib)
    save_topics(record, lib)
    save_relations(record, lib)
    lib.save_record(record)
    return record


__all__ = ["build_relations", "entity_id", "merge_records", "resolve_entities",
           "save_relations", "save_topics", "store_record"]
