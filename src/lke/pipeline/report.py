"""End-of-run summary."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from lke.config import Settings
from lke.extract import UsageTracker
from lke.pipeline.runner import DocReport


def write_report(settings: Settings, reports: list[DocReport], usage: UsageTracker,
                 started: datetime, dry_run: bool = False,
                 estimate: dict | None = None) -> Path:
    """reports/run-<time>.json (machine-readable) and .md (for people)."""
    finished = datetime.now()
    stamp = started.strftime("%Y%m%d-%H%M%S")
    folder = settings.path("reports")
    folder.mkdir(parents=True, exist_ok=True)
    cost = usage.cost(settings.llm.prices_per_million)
    totals = {
        "documents": len(reports),
        "pages": sum(r.pages for r in reports),
        "sections": sum(r.sections for r in reports),
        "sections_failed": sum(r.sections_failed for r in reports),
        "records_saved": sum(r.records_saved for r in reports),
        "records_for_review": sum(r.records_for_review for r in reports),
        "regenerated": sum(r.regenerated for r in reports),
    }
    data = {
        "started": started.isoformat(timespec="seconds"),
        "finished": finished.isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "totals": totals,
        "usage": usage.to_dict(),
        "approx_cost_usd": cost,
        "estimate": estimate,
        "documents": [asdict(r) for r in reports],
    }
    json_path = folder / f"run-{stamp}.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# Run {stamp}{' (dry run)' if dry_run else ''}",
        "",
        f"- Documents: {totals['documents']}, pages: {totals['pages']}, "
        f"sections: {totals['sections']}",
        f"- Records saved: {totals['records_saved']}, waiting for review: "
        f"{totals['records_for_review']}, reworded after overlap check: {totals['regenerated']}",
        f"- Failed sections: {totals['sections_failed']}",
        f"- Approximate API cost: ${cost:.2f}",
    ]
    if estimate:
        lines.append(f"- Estimated cost of a full run: ${estimate['low_usd']:.2f} - "
                     f"${estimate['high_usd']:.2f} for {estimate['sections']} sections")
    lines += ["", "| File | Status | Pages | Sections | Saved | Review | Failed |",
              "|---|---|---|---|---|---|---|"]
    for r in reports:
        lines.append(f"| {r.filename} | {r.status} | {r.pages} | {r.sections} | "
                     f"{r.records_saved} | {r.records_for_review} | {r.sections_failed} |")
    errors = [(r.filename, e) for r in reports for e in r.errors]
    if errors or any(r.message for r in reports):
        lines += ["", "## Problems", ""]
        lines += [f"- **{r.filename}**: {r.message}" for r in reports if r.message]
        lines += [f"- **{name}**: {e}" for name, e in errors]
    md_path = folder / f"run-{stamp}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path
