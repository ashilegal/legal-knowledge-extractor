import json
import logging
import os
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from lke import __version__
from lke.config import Settings, load_settings
from lke.ingest import scan_inbox
from lke.link import store_record
from lke.models import parse_record
from lke.pipeline.batch import library_path, run_batch
from lke.pipeline.report import write_report
from lke.pipeline.runner import reprocess as reprocess_doc
from lke.pipeline.stages import run_ingest, run_structure
from lke.store import Checkpoint, Library, Stage
from lke.store.exporter import export_csv, export_jsonl
from lke.store.html_report import export_html
from lke.store.knowledge_export import export_knowledge

app = typer.Typer(help="Legal Knowledge Extractor: PDFs -> structured, searchable knowledge "
                       "records.", no_args_is_help=True)
review_app = typer.Typer(help="Records that need a human decision before entering the library.")
app.add_typer(review_app, name="review")
console = Console()


def _settings() -> Settings:
    settings = load_settings()
    settings.ensure_dirs()
    return settings


def open_library() -> Library:
    return Library(library_path(_settings()))


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed logs.")):
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")


@app.command()
def version():
    """Show the installed version."""
    typer.echo(f"legal-knowledge-extractor {__version__}")


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Read, structure and classify only; estimate the cost. "
                                      "No LLM calls."),
    workers: int = typer.Option(0, help="Documents processed in parallel (0 = config value)."),
    only: str = typer.Option("", help="Process only inbox files whose name contains this."),
):
    """Process every PDF in the inbox. Safe to stop and run again: finished work is kept."""
    settings = _settings()
    inbox = scan_inbox(settings.path("inbox"))
    files = [f for f in inbox if only.lower() in f.name.lower()]
    if not inbox:
        console.print(f"No PDFs found in {settings.path('inbox')}")
        raise typer.Exit()
    if not files:
        console.print(f"No PDF in the inbox has '{only}' in its name. Files in the inbox:")
        for f in inbox:
            console.print(f"  {f.name}")
        raise typer.Exit(1)
    provider = settings.llm.provider
    if not dry_run and provider == "anthropic" and not (
            os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
        console.print("[red]ANTHROPIC_API_KEY is not set.[/red] Add it to the .env file, or set "
                      "llm.provider: ollama in config.yaml to use a free local model.")
        raise typer.Exit(1)
    if not dry_run and provider == "ollama":
        from lke.extract import LLMSetupError
        from lke.extract.ollama_client import OllamaLLM
        try:
            OllamaLLM(settings.llm).check()
        except LLMSetupError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        console.print(f"Using local model {settings.llm.ollama_model} (free; slower than the API)")

    started = datetime.now()
    console.print(f"{'Dry run' if dry_run else 'Processing'}: {len(files)} file(s)")

    def progress(report):
        colour = {"done": "green", "partial": "yellow", "estimated": "cyan"}.get(
            report.status, "red")
        console.print(f"  [{colour}]{report.status:>11}[/{colour}]  {report.filename}  "
                      f"sections={report.sections} saved={report.records_saved} "
                      f"review={report.records_for_review} failed={report.sections_failed}")

    result = run_batch(settings, files, dry_run=dry_run, workers=workers or None,
                       on_done=progress)
    report_path = write_report(settings, result.reports, result.usage, started, dry_run,
                               result.estimate)
    if result.fatal:
        console.print(f"[red]Stopped: {result.fatal}[/red]")
    if result.estimate:
        e = result.estimate
        console.print(f"Sections to send to the LLM: {e['sections']} "
                      f"(~{e['section_tokens']:,} tokens of text)")
        if settings.llm.provider == "ollama":
            console.print("Cost: $0 (local model). Time depends on your computer.")
        else:
            console.print(f"Estimated cost: ${e['low_usd']:.2f} - ${e['high_usd']:.2f}")
    elif not dry_run:
        console.print(f"Approximate API cost of this run: "
                      f"${result.usage.cost(settings.llm.prices_per_million):.2f}")
    console.print(f"Report: {report_path}")
    if result.fatal:
        raise typer.Exit(1)


@app.command()
def ingest():
    """Stage 1 only: read every PDF in the inbox into work/<doc_id>/pages.jsonl."""
    settings = _settings()
    files = scan_inbox(settings.path("inbox"))
    if not files:
        console.print(f"No PDFs found in {settings.path('inbox')}")
        raise typer.Exit()

    table = Table(title=f"Ingest ({len(files)} file(s))")
    for col in ("file", "doc_id", "pages", "ocr", "status", "notes"):
        table.add_column(col)
    with Library(library_path(settings)) as lib:
        for path in files:
            console.print(f"Reading {path.name} ...")
            o = run_ingest(path, settings, lib)
            colour = {"done": "green", "skipped": "cyan"}.get(o.status, "red")
            table.add_row(o.filename, o.doc_id, str(o.pages), str(o.ocr_pages),
                          f"[{colour}]{o.status}[/{colour}]", o.message)
    console.print(table)
    console.print(f"Output: {settings.path('work')}")


@app.command()
def structure():
    """Stages 2-3 only: detect topics/subtopics and split ingested PDFs into sections."""
    settings = _settings()
    with Library(library_path(settings)) as lib:
        cp = Checkpoint(lib)
        docs = [d for d in lib.list_documents() if cp.is_done(d["doc_id"], Stage.INGEST)]
        if not docs:
            console.print("Nothing ingested yet. Run: lke ingest")
            raise typer.Exit()
        table = Table(title="Structure")
        for col in ("file", "sections", "pages", "topics"):
            table.add_column(col)
        for d in docs:
            sections = run_structure(d["doc_id"], settings, lib)
            topics = sorted({s.topic_path[0] for s in sections if s.topic_path})
            table.add_row(d["filename"], str(len(sections)), str(d["page_count"]),
                          ", ".join(topics[:5]) + (" ..." if len(topics) > 5 else ""))
    console.print(table)
    console.print(f"Output: {settings.path('work')}/<doc_id>/sections.jsonl")


@app.command()
def status():
    """Show documents, stage progress and record counts."""
    with open_library() as lib:
        docs = lib.list_documents()
        table = Table(title=f"Documents ({len(docs)})")
        for col in ("doc_id", "filename", "pages", "status", "note"):
            table.add_column(col)
        for d in docs:
            table.add_row(d["doc_id"], d["filename"], str(d["page_count"]), d["status"],
                          d["error"] or "")
        console.print(table)

        stages = Checkpoint(lib).summary()
        if stages:
            st = Table(title="Stages (documents or sections)")
            for col in ("stage", "done", "failed", "running"):
                st.add_column(col)
            for name, counts in stages.items():
                st.add_row(name, *(str(counts.get(k, 0)) for k in ("done", "failed", "running")))
            console.print(st)

        counts = lib.count_records()
        console.print(f"Records: {sum(counts.values())} {counts if counts else ''}")
        console.print(f"Entities: {lib.count_entities() or 0}")
        console.print(f"Waiting for review: {len(lib.list_reviews())}")
        console.print(f"Library: {lib.path}")


@app.command()
def failures():
    """List failed documents and sections with the error. 'lke run' retries them."""
    with open_library() as lib:
        rows = Checkpoint(lib).failures()
        if not rows:
            console.print("No failures.")
            return
        table = Table(title=f"Failures ({len(rows)})")
        for col in ("doc_id", "stage", "unit", "attempts", "error"):
            table.add_column(col)
        for r in rows:
            table.add_row(r["doc_id"], r["stage"], r["unit_id"], str(r["attempts"]),
                          (r["error"] or "")[:150])
        console.print(table)
        console.print("Run 'lke run' again to retry them.")


@app.command()
def show(record_id: str):
    """Print one record as JSON, with its relationships."""
    with open_library() as lib:
        record = lib.get_record(record_id)
        if record is None:
            console.print(f"No record {record_id}")
            raise typer.Exit(1)
        console.print_json(record.model_dump_json())
        rels = lib.relations_of(record_id)
        if rels:
            console.print("Relationships:")
            for r in rels:
                console.print(f"  {r['from_id']} --{r['relation']}--> {r['to_id']}")


@app.command()
def topics():
    """Topic -> subtopic tree with record counts."""
    with open_library() as lib:
        rows = lib.topic_tree()
        children: dict[str, list] = {}
        for r in rows:
            children.setdefault(r["parent_id"], []).append(r)
        for top in children.get(None, []):
            console.print(f"[bold]{top['name']}[/bold] ({top['n']})")
            for sub in children.get(top["topic_id"], []):
                console.print(f"    {sub['name']} ({sub['n']})")


@app.command()
def search(query: str, limit: int = 20,
           semantic: bool = typer.Option(False, help="Meaning-based search (needs the "
                                                     "'search' extra).")):
    """Search the knowledge library (keyword by default)."""
    with open_library() as lib:
        if semantic:
            from lke.search import SemanticIndex, default_embedder
            index = SemanticIndex(lib, default_embedder(), lib.path.parent / "embeddings.npz")
            for h in index.search(query, limit):
                console.print(f"{h['score']:.3f}  {h['title']}  ({h['record_id']})")
            return
        hits = lib.search(query, limit)
        if not hits:
            console.print("No results.")
        for h in hits:
            console.print(f"[bold]{h['record_type']}[/bold] {h['title']}  ({h['record_id']})")
            console.print(f"    {h['snippet']}")


@app.command()
def export(out: Path = typer.Option(None, help="Folder (default: data/library/export)."),
           csv: bool = typer.Option(True, help="Also write records.csv for Excel.")):
    """Export: knowledge_records.json (agreed format), library.html (to read), JSONL, CSV."""
    settings = _settings()
    folder = out or settings.path("library") / "export"
    with Library(library_path(settings)) as lib:
        html = export_html(lib, folder / "library.html")
        paths = export_knowledge(lib, folder) + export_jsonl(lib, folder)
        if csv:
            paths.append(export_csv(lib, folder / "records.csv"))
    for p in paths:
        console.print(f"Wrote {p}")
    console.print(f"[bold]Open this file to read the library:[/bold] {html}")


@app.command("open")
def open_library_page():
    """Create library.html and open it in your web browser."""
    import webbrowser
    settings = _settings()
    folder = settings.path("library") / "export"
    with Library(library_path(settings)) as lib:
        html = export_html(lib, folder / "library.html")
        export_knowledge(lib, folder)
    console.print(f"Opening {html}")
    console.print(f"JSON records: {folder / 'knowledge_records.json'}")
    webbrowser.open(html.resolve().as_uri())


@app.command()
def reprocess(doc_id: str, from_stage: str = typer.Option(
        "compose", "--from", help="'extract' (redo both LLM passes) or 'compose' (pass 2 only).")):
    """Redo a document after changing prompts or models. Then run 'lke run'."""
    if from_stage not in ("extract", "compose"):
        console.print("--from must be 'extract' or 'compose'")
        raise typer.Exit(1)
    settings = _settings()
    with Library(library_path(settings)) as lib:
        reprocess_doc(doc_id, settings, lib, from_stage)
    console.print(f"{doc_id} will be redone from '{from_stage}' on the next 'lke run'.")


@app.command()
def schemas(out: Path = typer.Option(Path("schemas"), help="Folder for the JSON schemas.")):
    """Write the JSON schema of each record type (for other tools that read the library)."""
    from lke.models import (CaseRecord, ComparisonRecord, ConceptRecord, ExampleRecord,
                            Relation, RuleRecord)
    out.mkdir(parents=True, exist_ok=True)
    for name, model in [("case", CaseRecord), ("concept", ConceptRecord), ("rule", RuleRecord),
                        ("example", ExampleRecord), ("comparison", ComparisonRecord),
                        ("relation", Relation)]:
        path = out / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2), encoding="utf-8")
        console.print(f"Wrote {path}")


# ---------- review queue ----------

@review_app.command("list")
def review_list(status: str = "pending"):
    """Records waiting for a decision."""
    with open_library() as lib:
        rows = lib.list_reviews(status)
        if not rows:
            console.print(f"No {status} reviews.")
            return
        table = Table(title=f"Review queue: {status} ({len(rows)})")
        for col in ("review_id", "type", "title", "reasons"):
            table.add_column(col)
        for r in rows:
            reasons = "; ".join(json.loads(r["reasons"]))
            table.add_row(r["review_id"], r["record_type"], r["title"][:60], reasons[:120])
        console.print(table)


@review_app.command("show")
def review_show(review_id: str):
    """Show a flagged record and why it was flagged."""
    with open_library() as lib:
        row = lib.get_review(review_id)
        if row is None:
            console.print(f"No review {review_id}")
            raise typer.Exit(1)
        console.print(f"Reasons: {'; '.join(json.loads(row['reasons']))}")
        console.print_json(row["data"])


@review_app.command("approve")
def review_approve(review_id: str):
    """Accept a flagged record into the library (merged with any existing record)."""
    with open_library() as lib:
        row = lib.get_review(review_id)
        if row is None:
            console.print(f"No review {review_id}")
            raise typer.Exit(1)
        record = parse_record(row["data"])
        record.flags.needs_review = False
        record.validation.status = "HUMAN_REVIEW"       # exported as PASS, approved by reviewer
        store_record(record, lib)
        lib.set_review_status(review_id, "approved")
        console.print(f"Approved -> {record.record_id}")


@review_app.command("reject")
def review_reject(review_id: str):
    """Discard a flagged record."""
    with open_library() as lib:
        if lib.get_review(review_id) is None:
            console.print(f"No review {review_id}")
            raise typer.Exit(1)
        lib.set_review_status(review_id, "rejected")
        console.print("Rejected.")


if __name__ == "__main__":
    app()
