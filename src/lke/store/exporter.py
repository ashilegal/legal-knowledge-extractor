"""JSONL / CSV export."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from lke.store.db import Library, record_title


def export_jsonl(lib: Library, folder: Path) -> list[Path]:
    """records.jsonl (one record per line), relations.jsonl and topics.jsonl."""
    folder.mkdir(parents=True, exist_ok=True)
    records = folder / "records.jsonl"
    with records.open("w", encoding="utf-8") as f:
        for record in lib.iter_records():
            f.write(record.model_dump_json() + "\n")
    relations = folder / "relations.jsonl"
    with relations.open("w", encoding="utf-8") as f:
        for row in lib.all_relations():
            f.write(json.dumps({"from_id": row["from_id"], "relation": row["relation"],
                                "to_id": row["to_id"], "basis": row["basis"]},
                               ensure_ascii=False) + "\n")
    topics = folder / "topics.jsonl"
    with topics.open("w", encoding="utf-8") as f:
        for row in lib.topic_tree():
            f.write(json.dumps({"topic_id": row["topic_id"], "name": row["name"],
                                "parent_id": row["parent_id"], "records": row["n"]},
                               ensure_ascii=False) + "\n")
    return [records, relations, topics]


def export_csv(lib: Library, path: Path) -> Path:
    """One row per record: an overview to open in Excel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["record_id", "type", "title", "topic", "subtopic", "documents",
                         "pages", "proprietary", "needs_review"])
        for r in lib.iter_records():
            writer.writerow([
                r.record_id, r.record_type, record_title(r),
                r.topic.name if r.topic else "", r.subtopic.name if r.subtopic else "",
                " ".join(sorted(r.doc_ids)), " ".join(map(str, r.pages)),
                r.flags.proprietary, r.flags.needs_review,
            ])
    return path
