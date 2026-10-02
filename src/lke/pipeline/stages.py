"""Each stage: input file -> output file."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from lke.config import Settings
from lke.ingest import ingest_pdf, make_doc_id
from lke.ingest.pdf_reader import UnreadablePdfError
from lke.models import Document, DocumentStatus
from lke.store import Checkpoint, Library, Stage, atomic_write_json, atomic_write_jsonl


def work_dir(settings: Settings, doc_id: str) -> Path:
    return settings.path("work") / doc_id


@dataclass
class IngestOutcome:
    doc_id: str
    filename: str
    status: str                       # done | skipped | quarantined | failed
    pages: int = 0
    ocr_pages: int = 0
    message: str = ""


def run_ingest(path: Path, settings: Settings, lib: Library) -> IngestOutcome:
    """Stage 1: PDF -> work/<doc_id>/pages.jsonl + document.json."""
    cp = Checkpoint(lib)
    doc_id = make_doc_id(path)
    outcome = IngestOutcome(doc_id=doc_id, filename=path.name, status="done")

    if cp.is_done(doc_id, Stage.INGEST):
        existing = lib.get_document(doc_id)
        outcome.status = "skipped"
        outcome.pages = existing.page_count if existing else 0
        outcome.message = "already ingested"
        return outcome

    lib.upsert_document(Document(doc_id=doc_id, filename=path.name, source_path=str(path)))
    lib.set_document_status(doc_id, DocumentStatus.PROCESSING)
    cp.start(doc_id, Stage.INGEST)

    try:
        result = ingest_pdf(path, doc_id, settings)
    except UnreadablePdfError as e:
        quarantine(path, settings, str(e))
        cp.failed(doc_id, Stage.INGEST, str(e))
        lib.set_document_status(doc_id, DocumentStatus.QUARANTINED, str(e))
        outcome.status, outcome.message = "quarantined", str(e)
        return outcome
    except Exception as e:  # unexpected: keep the file, record the error, carry on
        cp.failed(doc_id, Stage.INGEST, f"{type(e).__name__}: {e}")
        lib.set_document_status(doc_id, DocumentStatus.FAILED, str(e))
        outcome.status, outcome.message = "failed", f"{type(e).__name__}: {e}"
        return outcome

    out = work_dir(settings, doc_id)
    pages_path = out / "pages.jsonl"
    atomic_write_jsonl(pages_path, [p.model_dump() for p in result.pages])
    atomic_write_json(out / "document.json", {
        "doc_id": doc_id,
        "filename": path.name,
        "source_path": str(path),
        "page_count": result.page_count,
        "ocr_pages": result.ocr_pages,
        "ocr_failed_pages": result.ocr_failed_pages,
        "low_quality_pages": result.low_quality_pages,
        "empty_pages": result.empty_pages,
        "total_chars": sum(p.char_count for p in result.pages),
        "warnings": sorted(set(result.warnings)),
    })

    lib.upsert_document(Document(doc_id=doc_id, filename=path.name, source_path=str(path),
                                 page_count=result.page_count))
    cp.done(doc_id, Stage.INGEST, output_path=pages_path)

    outcome.pages = result.page_count
    outcome.ocr_pages = len(result.ocr_pages)
    notes = []
    if result.ocr_failed_pages:
        notes.append(f"{len(result.ocr_failed_pages)} scanned page(s) not OCR'd")
    if result.low_quality_pages:
        notes.append(f"{len(result.low_quality_pages)} low-quality OCR page(s)")
    if result.empty_pages:
        notes.append(f"{len(result.empty_pages)} empty page(s)")
    outcome.message = "; ".join(notes)
    return outcome


def quarantine(path: Path, settings: Settings, reason: str) -> Path:
    """Move an unreadable file out of the inbox and note why."""
    target_dir = settings.path("quarantine")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    shutil.move(str(path), target)
    (target_dir / f"{path.name}.error.txt").write_text(reason, encoding="utf-8")
    return target
