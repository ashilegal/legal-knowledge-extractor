"""case->law, case->principle, example->concept ..."""

from __future__ import annotations

from lke.extract.record_composer import record_id_for
from lke.link.entity_resolver import entity_id
from lke.models import AnyRecord, Relation, RelationType
from lke.store import Library

_RELATION_NAMES = {r.value for r in RelationType}


def save_topics(record: AnyRecord, lib: Library) -> None:
    if record.topic:
        lib.upsert_topic(record.topic.id, record.topic.name)
    if record.subtopic:
        lib.upsert_topic(record.subtopic.id, record.subtopic.name,
                         record.topic.id if record.topic else None)


def build_relations(record: AnyRecord) -> list[Relation]:
    """Edges of the knowledge graph that this record contributes."""
    rid = record.record_id
    out: list[Relation] = []
    parent = record.subtopic or record.topic
    if parent:
        out.append(Relation(from_id=rid, relation=RelationType.PART_OF, to_id=parent.id))
    if record.subtopic and record.topic:
        out.append(Relation(from_id=record.subtopic.id, relation=RelationType.PART_OF,
                            to_id=record.topic.id))
    f = record.fields
    for law in getattr(f, "laws", []):
        if law.entity_id:
            out.append(Relation(from_id=rid, relation=RelationType.INTERPRETS, to_id=law.entity_id))
    for law in getattr(f, "provisions", []):
        if law.entity_id:
            out.append(Relation(from_id=rid, relation=RelationType.DEFINES, to_id=law.entity_id))
    for ref in f.related:
        target = (entity_id("STATUTE", ref.name) if ref.type == "STATUTE"
                  else record_id_for(ref.type, ref.name))
        if not target or target == rid:
            continue
        ref.record_id = target
        relation = ref.relation if ref.relation in _RELATION_NAMES else "related_to"
        out.append(Relation(from_id=rid, relation=RelationType(relation), to_id=target,
                            basis="source"))
    if record.record_type == "EXAMPLE":
        for name in f.concept_illustrated:
            out.append(Relation(from_id=rid, relation=RelationType.ILLUSTRATES,
                                to_id=record_id_for("CONCEPT", name)))
    return out


def save_relations(record: AnyRecord, lib: Library) -> int:
    rels = build_relations(record)
    for rel in rels:
        lib.add_relation(rel)
    return len(rels)
