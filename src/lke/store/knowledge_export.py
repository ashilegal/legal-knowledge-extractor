"""Records in the agreed output format:

{ topic, subtopic, content_type, title, knowledge{}, related_concepts[], related_cases[],
  source{document_id, original_file, page_start, page_end},
  validation{status: PASS | REGENERATE | HUMAN_REVIEW, similarity_score, reason} }
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from lke.models import AnyRecord, parse_record
from lke.models.records import ComparisonItem, Statement
from lke.store.db import Library, record_title


def _texts(value: Any) -> list[str]:
    if isinstance(value, Statement):
        return [value.text]
    return [v.text for v in value or [] if isinstance(v, Statement)]


def _one(value: Any) -> str:
    texts = _texts(value)
    return texts[0] if texts else ""


def _laws(laws) -> list[str]:
    return [", ".join(x for x in (l.provision, l.statute) if x) for l in laws]


def knowledge_of(record: AnyRecord) -> dict[str, Any]:
    f = record.fields
    t = record.record_type
    if t == "CASE":
        return {
            "case_name": f.case_name,
            "citation": f.citation or "",
            "court": f.court or "",
            "year": f.date.value[:4] if f.date else "",
            "parties": [{"name": p.name, "role": p.role} for p in f.parties],
            "material_facts": _texts(f.material_facts),
            "legal_issue": _texts(f.legal_issues),
            "relevant_law": _laws(f.laws),
            "decision": _one(f.decision),
            "legal_principles": _texts(f.principles),
            "important_factors": _texts(f.important_factors),
        }
    if t == "CONCEPT":
        return {"concept_name": f.concept_name, "definition": _one(f.definition),
                "key_points": _texts(f.key_points),
                "important_factors": _texts(f.important_factors)}
    if t == "RULE":
        quotes = [l.quoted_provision for l in f.provisions if l.quoted_provision]
        return {"rule_name": f.rule_name, "relevant_provision": _laws(f.provisions),
                "requirements": _texts(f.requirements), "conditions": _texts(f.conditions),
                "exceptions": _texts(f.exceptions),
                "quoted_provision": quotes[0] if quotes else ""}
    if t == "EXAMPLE":
        return {"scenario": _one(f.scenario), "concept_illustrated": f.concept_illustrated,
                "important_facts": _texts(f.important_facts), "result": _one(f.result)}
    return {"title": f.title, "compared": f.subjects, "aspects": f.dimensions,
            "comparison": [{"subject": i.subject, "aspect": i.attribute, "value": i.value}
                           for i in f.items if isinstance(i, ComparisonItem)],
            "key_differences": _texts(f.key_differences)}


def to_output(record: AnyRecord, files: dict[str, str], status: str | None = None,
              reason: str | None = None, review_id: str | None = None) -> dict[str, Any]:
    by_doc: dict[str, set[int]] = defaultdict(set)
    for ev in record.evidence:
        by_doc[ev.doc_id].update(ev.pages)
    sources = [{"document_id": doc, "original_file": files.get(doc, ""),
                "page_start": min(pages), "page_end": max(pages)}
               for doc, pages in by_doc.items()]
    f = record.fields
    related_cases = [r.name for r in f.related if r.type == "CASE"]
    related_concepts = [r.name for r in f.related if r.type != "CASE"]
    if record.record_type == "EXAMPLE":
        related_concepts += [c for c in f.concept_illustrated if c not in related_concepts]
    v = record.validation
    out = {
        "record_id": record.record_id,
        "topic": record.topic.name if record.topic else "",
        "subtopic": record.subtopic.name if record.subtopic else "",
        "content_type": record.record_type,
        "title": record_title(record),
        "knowledge": knowledge_of(record),
        "related_concepts": related_concepts,
        "related_cases": related_cases,
        "source": sources[0] if sources else {},
        "validation": {
            "status": status or v.status or "PASS",
            "similarity_score": v.similarity_score,
            "reason": reason if reason is not None else v.reason,
        },
    }
    if len(sources) > 1:                      # same case/rule found in several documents
        out["additional_sources"] = sources[1:]
    if review_id:
        out["review_id"] = review_id
    return out


def export_knowledge(lib: Library, folder: Path, include_review: bool = True) -> list[Path]:
    """knowledge_records.json (one list) and knowledge_records.jsonl (one record per line)."""
    files = {d["doc_id"]: d["filename"] for d in lib.list_documents()}
    rows = []
    for record in lib.iter_records():
        approved = record.validation.status == "HUMAN_REVIEW"     # approved by a person
        rows.append(to_output(record, files, status="PASS",
                              reason="approved by reviewer" if approved else None))
    if include_review:
        for row in lib.list_reviews("pending"):
            record = parse_record(row["data"])
            rows.append(to_output(record, files, status="HUMAN_REVIEW",
                                  reason="; ".join(json.loads(row["reasons"])),
                                  review_id=row["review_id"]))
    folder.mkdir(parents=True, exist_ok=True)
    as_json = folder / "knowledge_records.json"
    as_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    as_jsonl = folder / "knowledge_records.jsonl"
    as_jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                        encoding="utf-8")
    return [as_json, as_jsonl]
