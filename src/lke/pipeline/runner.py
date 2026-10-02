"""Runs stages, skips completed ones (resume)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from lke.classify import SectionClass
from lke.classify.llm_classifier import classify_with_llm
from lke.config import Settings
from lke.extract import JsonLLM, LLMError, LLMSetupError, compose_records, extract_facts
from lke.extract.fact_extractor import SectionFacts
from lke.extract.record_composer import build_record_pairs
from lke.link import store_record
from lke.models import AnyRecord, DocumentStatus, Section, make_id, parse_record
from lke.pipeline.stages import (
    load_sections,
    run_classify,
    run_ingest,
    run_structure,
    work_dir,
)
from lke.store import (
    Checkpoint,
    Library,
    Stage,
    atomic_write_json,
    read_json,
)
from lke.terms import protected_terms
from lke.validate import PASS, REGENERATE, SectionContext, validate

log = logging.getLogger(__name__)

# errors that make every further call pointless: stop the whole run
FATAL_ERRORS = (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
                anthropic.NotFoundError, LLMSetupError)


class FatalRunError(Exception):
    """Configuration problem (bad API key, unknown model): stop instead of failing every section."""


@dataclass
class SectionOutcome:
    section_id: str
    records: list[AnyRecord] = field(default_factory=list)      # passed validation
    review: list[AnyRecord] = field(default_factory=list)       # need a human
    error: str | None = None
    skipped_reason: str | None = None
    regenerated: int = 0
    build_errors: list[str] = field(default_factory=list)


@dataclass
class DocReport:
    doc_id: str
    filename: str
    status: str = "done"               # done | partial | skipped | quarantined | failed
    pages: int = 0
    sections: int = 0
    sections_skipped: int = 0
    sections_failed: int = 0
    records_saved: int = 0
    records_for_review: int = 0
    regenerated: int = 0
    errors: list[str] = field(default_factory=list)
    message: str = ""


def _facts_path(settings: Settings, doc_id: str, section_id: str) -> Path:
    return work_dir(settings, doc_id) / "facts" / f"{section_id}.json"


def _records_path(settings: Settings, doc_id: str, section_id: str) -> Path:
    return work_dir(settings, doc_id) / "records" / f"{section_id}.json"


def _low_quality_pages(settings: Settings, doc_id: str) -> set[int]:
    path = work_dir(settings, doc_id) / "document.json"
    return set(read_json(path).get("low_quality_pages", [])) if path.exists() else set()


def process_section(section: Section, cls: SectionClass, settings: Settings, llm: JsonLLM,
                    low_pages: set[int]) -> SectionOutcome:
    """Pass 1 + pass 2 + validation for one section. Pure work: no database access,
    so it can run in a thread. Results are cached in work/<doc>/facts and records."""
    out = SectionOutcome(section.section_id)
    facts_file = _facts_path(settings, section.doc_id, section.section_id)
    records_file = _records_path(settings, section.doc_id, section.section_id)
    try:
        if records_file.exists():                 # finished earlier but not yet stored
            data = read_json(records_file)
            out.records = [parse_record(r) for r in data["records"]]
            out.review = [parse_record(r) for r in data["review"]]
            out.build_errors = data.get("build_errors", [])
            return out
        if facts_file.exists():                                   # resume: no second LLM call
            facts = SectionFacts(**read_json(facts_file))
        else:
            facts = extract_facts(section, protected_terms(section.text), cls.types,
                                  settings, llm)
            atomic_write_json(facts_file, facts.model_dump())
        if not facts.items:
            out.skipped_reason = facts.skipped_reason or "no items extracted"
            return out

        ctx = SectionContext.build(section, low_pages)
        pending = list(facts.items)
        too_close: dict[str, list[str]] = {}
        attempt = 0
        while pending:
            composed = compose_records(pending, settings, llm, too_close or None)
            pairs, errors = build_record_pairs(
                section, facts.model_copy(update={"items": pending}), composed, settings)
            out.build_errors += errors
            next_round, too_close = [], {}
            for item, record in pairs:
                verdict = validate(record, ctx, item, settings.validation, attempt)
                if verdict.decision == REGENERATE:      # reword only the items that failed
                    next_round.append(item)
                    too_close[item.key] = verdict.too_close
                elif verdict.decision == PASS:
                    out.records.append(verdict.record)
                else:
                    out.review.append(verdict.record)
            out.regenerated += len(next_round)
            pending = next_round
            attempt += 1
        atomic_write_json(records_file, {
            "section_id": section.section_id,
            "records": [r.model_dump(mode="json") for r in out.records],
            "review": [r.model_dump(mode="json") for r in out.review],
            "build_errors": out.build_errors,
        })
    except FATAL_ERRORS as e:
        raise FatalRunError(f"{type(e).__name__}: {e}") from e
    except (LLMError, anthropic.APIError) as e:
        out.error = f"{type(e).__name__}: {e}"
    except Exception as e:                       # keep the batch alive, report the section
        log.exception("section %s failed", section.section_id)
        out.error = f"{type(e).__name__}: {e}"
    return out


def _store_outcome(out: SectionOutcome, section: Section, lib: Library, cp: Checkpoint,
                   settings: Settings) -> None:
    for record in out.records:
        store_record(record, lib)
    for record in out.review:
        review_id = make_id("rev", record.record_id, section.section_id)
        lib.add_review(review_id, record, section.doc_id, section.section_id)
        atomic_write_json(settings.path("review") / f"{review_id}.json",
                          record.model_dump(mode="json"))
    cp.done(section.doc_id, Stage.EXTRACT, section.section_id,
            _facts_path(settings, section.doc_id, section.section_id))
    cp.done(section.doc_id, Stage.COMPOSE, section.section_id,
            _records_path(settings, section.doc_id, section.section_id))
    cp.done(section.doc_id, Stage.LINK, section.section_id)


def process_document(doc_id: str, settings: Settings, lib: Library, llm: JsonLLM | None,
                     dry_run: bool = False) -> tuple[DocReport, list[Section],
                                                     dict[str, SectionClass]]:
    """Stages 2-8 for an ingested document. With dry_run, stops before any LLM call."""
    cp = Checkpoint(lib)
    doc = lib.get_document(doc_id)
    report = DocReport(doc_id, doc.filename if doc else doc_id, pages=doc.page_count if doc else 0)

    sections = run_structure(doc_id, settings, lib)
    classes = run_classify(doc_id, settings, lib, sections)
    report.sections = len(sections)

    if llm is not None and settings.llm.classify_with_llm and not dry_run:
        for s in sections:
            c = classes[s.section_id]
            if c.unclear and not c.skip:
                try:
                    classes[s.section_id] = classify_with_llm(s, c, settings, llm)
                except LLMError as e:
                    log.warning("LLM classification failed for %s: %s", s.section_id, e)

    todo = []
    for s in sections:
        c = classes[s.section_id]
        if c.skip:
            report.sections_skipped += 1
        elif not cp.is_done(doc_id, Stage.LINK, s.section_id):
            todo.append(s)
    if dry_run or llm is None:
        report.status = "estimated"
        return report, sections, classes

    lib.set_document_status(doc_id, DocumentStatus.PROCESSING)
    low_pages = _low_quality_pages(settings, doc_id)
    for s in todo:
        cp.start(doc_id, Stage.EXTRACT, s.section_id)

    workers = max(1, settings.llm.max_concurrent_requests)
    try:
        _run_sections(todo, classes, settings, llm, low_pages, lib, cp, report, workers)
    except FatalRunError as e:
        # leave a clear state behind: nothing 'running', document marked failed
        cp.recover_interrupted()
        lib.set_document_status(doc_id, DocumentStatus.FAILED, f"stopped: {e}")
        raise

    if report.sections_failed:
        report.status = "partial"
        lib.set_document_status(doc_id, DocumentStatus.FAILED,
                                f"{report.sections_failed} section(s) failed")
    else:
        lib.set_document_status(doc_id, DocumentStatus.DONE)
    return report, sections, classes


def _run_sections(todo, classes, settings, llm, low_pages, lib, cp, report, workers) -> None:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_section, s, classes[s.section_id], settings, llm,
                               low_pages): s for s in todo}
        for future, section in futures.items():
            out = future.result()                 # FatalRunError propagates and stops the run
            doc_id = section.doc_id
            if out.error:
                report.sections_failed += 1
                report.errors.append(f"{section.title} (p. {section.page_start}-"
                                     f"{section.page_end}): {out.error}")
                cp.failed(doc_id, Stage.EXTRACT, out.error, section.section_id)
                continue
            if out.skipped_reason:
                report.sections_skipped += 1
            _store_outcome(out, section, lib, cp, settings)
            report.errors += [f"{section.title}: could not build record {e}"
                              for e in out.build_errors]
            report.records_saved += len(out.records)
            report.records_for_review += len(out.review)
            report.regenerated += out.regenerated


def process_file(path: Path, settings: Settings, lib: Library, llm: JsonLLM | None,
                 dry_run: bool = False) -> tuple[DocReport, list[Section],
                                                 dict[str, SectionClass]]:
    ingest = run_ingest(path, settings, lib)
    if ingest.status in ("quarantined", "failed"):
        return DocReport(ingest.doc_id, path.name, status=ingest.status,
                         message=ingest.message), [], {}
    return process_document(ingest.doc_id, settings, lib, llm, dry_run)


def reprocess(doc_id: str, settings: Settings, lib: Library, from_stage: str) -> None:
    """Forget cached results so a document is redone from 'extract' or 'compose'
    (e.g. after changing prompts or models). Library records already saved are kept
    and will be merged with the new ones."""
    cp = Checkpoint(lib)
    folders = {"extract": ["facts", "records"], "compose": ["records"]}[from_stage]
    for name in folders:
        folder = work_dir(settings, doc_id) / name
        if folder.exists():
            for f in folder.glob("*.json"):
                f.unlink()
    stages = {"extract": [Stage.EXTRACT, Stage.COMPOSE, Stage.VALIDATE, Stage.LINK],
              "compose": [Stage.COMPOSE, Stage.VALIDATE, Stage.LINK]}[from_stage]
    for stage in stages:
        cp.reset(doc_id, stage)
    if from_stage == "compose":                  # keep facts but re-run the pipeline
        cp.reset(doc_id, Stage.EXTRACT)


__all__ = ["DocReport", "FatalRunError", "load_sections", "process_document", "process_file",
           "process_section", "reprocess"]
