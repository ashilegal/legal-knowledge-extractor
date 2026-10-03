"""SQLite tables + full-text search."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterator

from lke.models import AnyRecord, Document, DocumentStatus, Relation, parse_record
from lke.models.records import ComparisonItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id       TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    source_path  TEXT NOT NULL,
    page_count   INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'pending',
    error        TEXT,
    added_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stage_status (
    doc_id       TEXT NOT NULL,
    stage        TEXT NOT NULL,
    unit_id      TEXT NOT NULL DEFAULT '*',      -- '*' = whole document, else section id
    status       TEXT NOT NULL,                  -- running | done | failed
    attempts     INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    output_path  TEXT,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (doc_id, stage, unit_id)
);

CREATE TABLE IF NOT EXISTS topics (
    topic_id     TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    parent_id    TEXT REFERENCES topics(topic_id)
);

CREATE TABLE IF NOT EXISTS records (
    record_id    TEXT PRIMARY KEY,
    record_type  TEXT NOT NULL,
    title        TEXT NOT NULL,
    topic_id     TEXT,
    subtopic_id  TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    proprietary  INTEGER NOT NULL DEFAULT 0,
    data         TEXT NOT NULL,                  -- full record JSON
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_records_type  ON records(record_type);
CREATE INDEX IF NOT EXISTS idx_records_topic ON records(topic_id, subtopic_id);

CREATE TABLE IF NOT EXISTS evidence (
    record_id    TEXT NOT NULL REFERENCES records(record_id) ON DELETE CASCADE,
    evidence_id  TEXT NOT NULL,
    doc_id       TEXT NOT NULL,
    page_start   INTEGER NOT NULL,
    page_end     INTEGER NOT NULL,
    PRIMARY KEY (record_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_doc ON evidence(doc_id);

CREATE TABLE IF NOT EXISTS entities (
    entity_id    TEXT PRIMARY KEY,
    entity_type  TEXT NOT NULL,                  -- CASE, STATUTE, PROVISION, COURT, CONCEPT
    canonical    TEXT NOT NULL,
    aliases      TEXT NOT NULL DEFAULT '[]'      -- JSON list
);

CREATE TABLE IF NOT EXISTS relations (
    from_id      TEXT NOT NULL,
    relation     TEXT NOT NULL,
    to_id        TEXT NOT NULL,
    basis        TEXT NOT NULL DEFAULT 'source',
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (from_id, relation, to_id)
);
CREATE INDEX IF NOT EXISTS idx_relations_to ON relations(to_id);

CREATE TABLE IF NOT EXISTS review_queue (
    review_id    TEXT PRIMARY KEY,
    record_id    TEXT NOT NULL,                  -- library record it would merge into
    record_type  TEXT NOT NULL,
    title        TEXT NOT NULL,
    doc_id       TEXT NOT NULL,
    section_id   TEXT NOT NULL,
    reasons      TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected
    data         TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_review_status ON review_queue(status);

CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    record_id UNINDEXED, record_type UNINDEXED, title, body
);
"""


class Library:
    """The knowledge library: one SQLite file holding documents, records and progress."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = db_path
        self.conn = sqlite3.connect(db_path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")   # safe for several processes
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------- documents ----------

    def upsert_document(self, doc: Document) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO documents (doc_id, filename, source_path, page_count, status)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(doc_id) DO UPDATE SET
                       filename=excluded.filename,
                       source_path=excluded.source_path,
                       page_count=excluded.page_count,
                       updated_at=datetime('now')""",
                (doc.doc_id, doc.filename, doc.source_path, doc.page_count, doc.status.value),
            )

    def get_document(self, doc_id: str) -> Document | None:
        row = self.conn.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if row is None:
            return None
        return Document(
            doc_id=row["doc_id"], filename=row["filename"], source_path=row["source_path"],
            page_count=row["page_count"], status=DocumentStatus(row["status"]),
        )

    def set_document_status(
        self, doc_id: str, status: DocumentStatus, error: str | None = None
    ) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE documents SET status=?, error=?, updated_at=datetime('now') WHERE doc_id=?",
                (status.value, error, doc_id),
            )

    def list_documents(self, status: DocumentStatus | None = None) -> list[sqlite3.Row]:
        if status is None:
            return self.conn.execute("SELECT * FROM documents ORDER BY added_at").fetchall()
        return self.conn.execute(
            "SELECT * FROM documents WHERE status=? ORDER BY added_at", (status.value,)
        ).fetchall()

    # ---------- topics ----------

    def upsert_topic(self, topic_id: str, name: str, parent_id: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO topics (topic_id, name, parent_id) VALUES (?, ?, ?)
                   ON CONFLICT(topic_id) DO UPDATE SET name=excluded.name""",
                (topic_id, name, parent_id),
            )

    def topic_tree(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT t.topic_id, t.name, t.parent_id,
                      (SELECT COUNT(*) FROM records r
                        WHERE r.topic_id = t.topic_id OR r.subtopic_id = t.topic_id) AS n
               FROM topics t ORDER BY t.parent_id IS NOT NULL, t.name"""
        ).fetchall()

    # ---------- entities ----------

    def upsert_entity(self, entity_id: str, entity_type: str, canonical: str, alias: str) -> None:
        row = self.conn.execute(
            "SELECT aliases FROM entities WHERE entity_id=?", (entity_id,)).fetchone()
        aliases = json.loads(row["aliases"]) if row else []
        if alias and alias not in aliases:
            aliases.append(alias)
        with self.conn:
            self.conn.execute(
                """INSERT INTO entities (entity_id, entity_type, canonical, aliases)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(entity_id) DO UPDATE SET aliases=excluded.aliases""",
                (entity_id, entity_type, canonical, json.dumps(aliases, ensure_ascii=False)),
            )

    def count_entities(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT entity_type, COUNT(*) AS n FROM entities GROUP BY entity_type").fetchall()
        return {r["entity_type"]: r["n"] for r in rows}

    # ---------- review queue ----------

    def add_review(self, review_id: str, record: AnyRecord, doc_id: str, section_id: str) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO review_queue (review_id, record_id, record_type, title, doc_id,
                                             section_id, reasons, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(review_id) DO UPDATE SET data=excluded.data,
                       reasons=excluded.reasons, status='pending'""",
                (review_id, record.record_id, record.record_type, record_title(record), doc_id,
                 section_id, json.dumps(record.flags.reasons, ensure_ascii=False),
                 record.model_dump_json()),
            )

    def list_reviews(self, status: str = "pending") -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM review_queue WHERE status=? ORDER BY created_at", (status,)
        ).fetchall()

    def get_review(self, review_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM review_queue WHERE review_id=?", (review_id,)).fetchone()

    def set_review_status(self, review_id: str, status: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE review_queue SET status=? WHERE review_id=?",
                              (status, review_id))

    # ---------- records ----------

    def save_record(self, record: AnyRecord) -> None:
        """Insert or replace a record, its evidence rows and its search entry."""
        title = record_title(record)
        with self.conn:
            self.conn.execute("DELETE FROM records_fts WHERE record_id=?", (record.record_id,))
            self.conn.execute("DELETE FROM evidence WHERE record_id=?", (record.record_id,))
            self.conn.execute(
                """INSERT INTO records (record_id, record_type, title, topic_id, subtopic_id,
                                        needs_review, proprietary, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(record_id) DO UPDATE SET
                       record_type=excluded.record_type, title=excluded.title,
                       topic_id=excluded.topic_id, subtopic_id=excluded.subtopic_id,
                       needs_review=excluded.needs_review, proprietary=excluded.proprietary,
                       data=excluded.data, updated_at=datetime('now')""",
                (
                    record.record_id,
                    record.record_type,
                    title,
                    record.topic.id if record.topic else None,
                    record.subtopic.id if record.subtopic else None,
                    int(record.flags.needs_review),
                    int(record.flags.proprietary),
                    record.model_dump_json(),
                ),
            )
            self.conn.executemany(
                """INSERT INTO evidence (record_id, evidence_id, doc_id, page_start, page_end)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (record.record_id, ev.id, ev.doc_id, min(ev.pages), max(ev.pages))
                    for ev in record.evidence
                ],
            )
            self.conn.execute(
                "INSERT INTO records_fts (record_id, record_type, title, body) VALUES (?, ?, ?, ?)",
                (record.record_id, record.record_type, title, record_search_text(record)),
            )

    def get_record(self, record_id: str) -> AnyRecord | None:
        row = self.conn.execute(
            "SELECT data FROM records WHERE record_id=?", (record_id,)
        ).fetchone()
        return parse_record(row["data"]) if row else None

    def iter_records(self, record_type: str | None = None) -> Iterator[AnyRecord]:
        sql, args = "SELECT data FROM records", ()
        if record_type:
            sql, args = sql + " WHERE record_type=?", (record_type,)
        for row in self.conn.execute(sql + " ORDER BY record_id", args):
            yield parse_record(row["data"])

    def count_records(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT record_type, COUNT(*) AS n FROM records GROUP BY record_type"
        ).fetchall()
        return {r["record_type"]: r["n"] for r in rows}

    # ---------- relations ----------

    def add_relation(self, rel: Relation) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO relations (from_id, relation, to_id, basis, evidence_ids)
                   VALUES (?, ?, ?, ?, ?)""",
                (rel.from_id, rel.relation.value, rel.to_id, rel.basis.value,
                 json.dumps(rel.evidence_ids)),
            )

    def all_relations(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM relations ORDER BY from_id").fetchall()

    def relations_of(self, record_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM relations WHERE from_id=? OR to_id=?", (record_id, record_id)
        ).fetchall()

    # ---------- search ----------

    def search(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        """Keyword search over record titles and statement text."""
        return self.conn.execute(
            """SELECT record_id, record_type, title,
                      snippet(records_fts, 3, '[', ']', ' … ', 12) AS snippet
               FROM records_fts WHERE records_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (_fts_query(query), limit),
        ).fetchall()


def record_title(record: AnyRecord) -> str:
    f = record.fields
    for name in ("case_name", "concept_name", "rule_name", "title"):
        value = getattr(f, name, None)
        if value:
            return value
    return f.scenario.text[:80] if record.record_type == "EXAMPLE" else record.record_id


def record_search_text(record: AnyRecord) -> str:
    """Text indexed for search: the record's own wording plus its identifiers."""
    parts: list[str] = [record_title(record)]
    for st in record.statements():
        if isinstance(st, ComparisonItem):
            parts.append(f"{st.subject} {st.attribute} {st.value}")
        else:
            parts.append(st.text)
    for name in ("laws", "provisions"):
        for law in getattr(record.fields, name, []) or []:
            parts.append(f"{law.statute} {law.provision}")
    for name in ("court", "citation"):
        value = getattr(record.fields, name, None)
        if value:
            parts.append(value)
    if record.subtopic:
        parts.append(record.subtopic.name)
    if record.topic:
        parts.append(record.topic.name)
    return "\n".join(parts)


def _fts_query(query: str) -> str:
    """Treat each word as a literal term so punctuation like '25F' or 'v.' is safe."""
    words = [w.replace('"', "") for w in query.split()]
    return " ".join(f'"{w}"' for w in words if w)
