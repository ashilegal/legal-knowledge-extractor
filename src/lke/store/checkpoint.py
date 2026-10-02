"""Stage status per document/section."""

from __future__ import annotations

import json
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any

from lke.store.db import Library

WHOLE_DOCUMENT = "*"


class Stage(str, Enum):
    INGEST = "ingest"
    STRUCTURE = "structure"
    SECTION = "section"
    CLASSIFY = "classify"
    EXTRACT = "extract"
    COMPOSE = "compose"
    VALIDATE = "validate"
    LINK = "link"


class StageState(str, Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Checkpoint:
    """Records which stage has finished for which document/section, so runs can resume."""

    def __init__(self, library: Library):
        self.conn = library.conn

    def is_done(self, doc_id: str, stage: Stage, unit_id: str = WHOLE_DOCUMENT) -> bool:
        return self.state(doc_id, stage, unit_id) == StageState.DONE

    def state(
        self, doc_id: str, stage: Stage, unit_id: str = WHOLE_DOCUMENT
    ) -> StageState | None:
        row = self.conn.execute(
            "SELECT status FROM stage_status WHERE doc_id=? AND stage=? AND unit_id=?",
            (doc_id, stage.value, unit_id),
        ).fetchone()
        return StageState(row["status"]) if row else None

    def attempts(self, doc_id: str, stage: Stage, unit_id: str = WHOLE_DOCUMENT) -> int:
        row = self.conn.execute(
            "SELECT attempts FROM stage_status WHERE doc_id=? AND stage=? AND unit_id=?",
            (doc_id, stage.value, unit_id),
        ).fetchone()
        return row["attempts"] if row else 0

    def start(self, doc_id: str, stage: Stage, unit_id: str = WHOLE_DOCUMENT) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO stage_status (doc_id, stage, unit_id, status, attempts)
                   VALUES (?, ?, ?, 'running', 1)
                   ON CONFLICT(doc_id, stage, unit_id) DO UPDATE SET
                       status='running', attempts=attempts+1, error=NULL,
                       updated_at=datetime('now')""",
                (doc_id, stage.value, unit_id),
            )

    def done(
        self,
        doc_id: str,
        stage: Stage,
        unit_id: str = WHOLE_DOCUMENT,
        output_path: Path | None = None,
    ) -> None:
        self._set(doc_id, stage, unit_id, StageState.DONE, None,
                  str(output_path) if output_path else None)

    def failed(
        self, doc_id: str, stage: Stage, error: str, unit_id: str = WHOLE_DOCUMENT
    ) -> None:
        self._set(doc_id, stage, unit_id, StageState.FAILED, error[:2000], None)

    def failures(self, doc_id: str | None = None) -> list[Any]:
        sql = "SELECT * FROM stage_status WHERE status='failed'"
        args: tuple = ()
        if doc_id:
            sql, args = sql + " AND doc_id=?", (doc_id,)
        return self.conn.execute(sql + " ORDER BY updated_at", args).fetchall()

    def reset(self, doc_id: str, stage: Stage | None = None) -> None:
        """Forget progress so the document (or one stage of it) is processed again."""
        with self.conn:
            if stage is None:
                self.conn.execute("DELETE FROM stage_status WHERE doc_id=?", (doc_id,))
            else:
                self.conn.execute(
                    "DELETE FROM stage_status WHERE doc_id=? AND stage=?", (doc_id, stage.value)
                )

    def recover_interrupted(self) -> int:
        """After a crash, anything still 'running' was interrupted: mark it failed to retry."""
        with self.conn:
            cur = self.conn.execute(
                """UPDATE stage_status SET status='failed', error='interrupted',
                       updated_at=datetime('now') WHERE status='running'"""
            )
        return cur.rowcount

    def summary(self) -> dict[str, dict[str, int]]:
        rows = self.conn.execute(
            "SELECT stage, status, COUNT(*) AS n FROM stage_status GROUP BY stage, status"
        ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["stage"], {})[r["status"]] = r["n"]
        return out

    def _set(self, doc_id, stage, unit_id, state, error, output_path) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO stage_status (doc_id, stage, unit_id, status, error, output_path)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(doc_id, stage, unit_id) DO UPDATE SET
                       status=excluded.status, error=excluded.error,
                       output_path=COALESCE(excluded.output_path, output_path),
                       updated_at=datetime('now')""",
                (doc_id, stage.value, unit_id, state.value, error, output_path),
            )


# ---------- safe file writing ----------

def atomic_write_text(path: Path, text: str) -> None:
    """Write to a temp file, then rename: a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2, default=str))


def atomic_write_jsonl(path: Path, rows: list[Any]) -> None:
    lines = (json.dumps(r, ensure_ascii=False, default=str) for r in rows)
    atomic_write_text(path, "\n".join(lines) + ("\n" if rows else ""))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[Any]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
