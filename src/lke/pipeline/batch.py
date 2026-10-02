"""Many PDFs in parallel."""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from lke.classify import SectionClass
from lke.config import Settings, load_settings
from lke.extract import UsageTracker, make_llm
from lke.extract.llm_client import ModelUsage
from lke.models import Section
from lke.pipeline.runner import DocReport, FatalRunError, process_file
from lke.store import Checkpoint, Library

log = logging.getLogger(__name__)

PROMPT_TOKENS = 2500          # instructions + metadata per call (approx.)
FACTS_OUTPUT_SHARE = (0.25, 0.6)   # pass-1 output as a share of section tokens (low, high)
THINKING_OVERHEAD = (1.2, 2.0)     # extra output from model reasoning (low, high)


@dataclass
class BatchResult:
    reports: list[DocReport] = field(default_factory=list)
    usage: UsageTracker = field(default_factory=UsageTracker)
    fatal: str | None = None
    estimate: dict | None = None


def library_path(settings: Settings) -> Path:
    return settings.path("library") / "library.db"


def estimate_cost(settings: Settings, sections: list[Section],
                  classes: dict[str, SectionClass]) -> dict:
    """Rough range for pass 1 + pass 2 over the sections that will be sent to the LLM."""
    todo = [s for s in sections if not classes[s.section_id].skip]
    tokens = sum(s.token_estimate for s in todo)
    p = settings.llm.prices_per_million
    in1, out1 = p.get(settings.llm.extract_model, (0, 0))
    in2, out2 = p.get(settings.llm.compose_model, (0, 0))
    result = {"sections": len(todo), "section_tokens": tokens}
    for label, share, think in (("low", FACTS_OUTPUT_SHARE[0], THINKING_OVERHEAD[0]),
                                ("high", FACTS_OUTPUT_SHARE[1], THINKING_OVERHEAD[1])):
        facts = tokens * share
        cost = ((tokens + PROMPT_TOKENS * len(todo)) * in1 + facts * think * out1
                + (facts + PROMPT_TOKENS * len(todo)) * in2 + facts * think * out2) / 1e6
        result[f"{label}_usd"] = round(cost, 2)
    return result


def _run_one(path: str, root: str, dry_run: bool) -> tuple[DocReport, dict, list, dict]:
    """Worker-process entry point: own settings, library connection and API client."""
    settings = load_settings(Path(root) / "config.yaml")
    llm = None if dry_run else make_llm(settings.llm)
    with Library(library_path(settings)) as lib:
        report, sections, classes = process_file(Path(path), settings, lib, llm, dry_run)
    usage = llm.usage.to_dict() if llm else {}
    return report, usage, [s.model_dump() for s in sections], \
        {k: v.model_dump() for k, v in classes.items()}


def run_batch(settings: Settings, files: list[Path], dry_run: bool = False,
              workers: int | None = None,
              on_done: Callable[[DocReport], None] | None = None) -> BatchResult:
    """Process files one document per worker. Safe to stop and start again at any time."""
    result = BatchResult()
    with Library(library_path(settings)) as lib:
        recovered = Checkpoint(lib).recover_interrupted()
        if recovered:
            log.info("%d unfinished unit(s) from a previous run will be redone", recovered)

    all_sections: list[Section] = []
    all_classes: dict[str, SectionClass] = {}
    workers = workers or settings.batch.parallel_documents

    def collect(report, usage, sections, classes):
        result.reports.append(report)
        for model, counts in usage.items():
            target = result.usage.by_model.setdefault(model, ModelUsage())
            for k, v in counts.items():
                setattr(target, k, getattr(target, k) + v)
        all_sections.extend(Section(**s) for s in sections)
        all_classes.update({k: SectionClass(**v) for k, v in classes.items()})
        if on_done:
            on_done(report)

    try:
        if workers <= 1 or len(files) <= 1:
            for f in files:
                collect(*_run_one(str(f), str(settings.root), dry_run))
        else:
            done: set[str] = set()
            try:
                with ProcessPoolExecutor(max_workers=workers) as pool:
                    futures = {pool.submit(_run_one, str(f), str(settings.root), dry_run): f
                               for f in files}
                    for fut in as_completed(futures):
                        collect(*fut.result())
                        done.add(str(futures[fut]))
            except (BrokenProcessPool, OSError) as e:
                log.warning("parallel processing unavailable (%s); continuing one by one", e)
                for f in files:
                    if str(f) not in done:
                        collect(*_run_one(str(f), str(settings.root), dry_run))
    except FatalRunError as e:
        result.fatal = str(e)
    if dry_run:
        result.estimate = estimate_cost(settings, all_sections, all_classes)
    return result
