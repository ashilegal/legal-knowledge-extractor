"""Each stage: input file -> output file."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from lke.classify import SectionClass, classify_section
from lke.config import Settings
from lke.ingest import ingest_pdf, make_doc_id
from lke.ingest.pdf_reader import UnreadablePdfError
from lke.models import Document, DocumentStatus, Page, Section
from lke.store import (
    Checkpoint,
    Library,
    Stage,
    atomic_write_json,
    atomic_write_jsonl,
    read_jsonl,
)
from lke.structure import build_tree, clean_title, find_headings, make_sections


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
        "table_pages": result.table_pages,
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


def load_pages(settings: Settings, doc_id: str) -> list[Page]:
    return [Page(**row) for row in read_jsonl(work_dir(settings, doc_id) / "pages.jsonl")]


def load_sections(settings: Settings, doc_id: str) -> list[Section]:
    return [Section(**row) for row in read_jsonl(work_dir(settings, doc_id) / "sections.jsonl")]


def run_structure(doc_id: str, settings: Settings, lib: Library) -> list[Section]:
    """Stages 2+3: pages -> topic tree (structure.json) -> sections (sections.jsonl)."""
    cp = Checkpoint(lib)
    if cp.is_done(doc_id, Stage.SECTION):
        return load_sections(settings, doc_id)

    cp.start(doc_id, Stage.STRUCTURE)
    try:
        doc = lib.get_document(doc_id)
        pdf_path = Path(doc.source_path) if doc else None
        doc_title = clean_title(Path(doc.filename).stem) if doc else doc_id
        pages = load_pages(settings, doc_id)
        cfg = settings.sectioning

        source, headings = find_headings(pages, pdf_path, cfg.max_heading_levels)
        tree = build_tree(doc_id, doc_title, headings)
        sections = make_sections(doc_id, pages, headings, doc_title, cfg)
    except Exception as e:
        cp.failed(doc_id, Stage.STRUCTURE, f"{type(e).__name__}: {e}")
        raise

    out = work_dir(settings, doc_id)
    atomic_write_json(out / "structure.json", {
        "doc_id": doc_id,
        "title": doc_title,
        "heading_source": source,
        "heading_count": len(headings),
        "section_count": len(sections),
        "tree": tree.to_dict(),
    })
    atomic_write_jsonl(out / "sections.jsonl", [s.model_dump() for s in sections])
    cp.done(doc_id, Stage.STRUCTURE, output_path=out / "structure.json")
    cp.done(doc_id, Stage.SECTION, output_path=out / "sections.jsonl")
    return sections


def load_classes(settings: Settings, doc_id: str) -> dict[str, SectionClass]:
    rows = read_jsonl(work_dir(settings, doc_id) / "classified.jsonl")
    return {r["section_id"]: SectionClass(**r) for r in rows}


def run_classify(doc_id: str, settings: Settings, lib: Library,
                 sections: list[Section]) -> dict[str, SectionClass]:
    """Stage 4: content types per section (free rules), written to classified.jsonl."""
    cp = Checkpoint(lib)
    if cp.is_done(doc_id, Stage.CLASSIFY):
        return load_classes(settings, doc_id)
    cp.start(doc_id, Stage.CLASSIFY)
    classes = {s.section_id: classify_section(s) for s in sections}
    path = work_dir(settings, doc_id) / "classified.jsonl"
    atomic_write_jsonl(path, [c.model_dump() for c in classes.values()])
    cp.done(doc_id, Stage.CLASSIFY, output_path=path)
    return classes
