import typer
from rich.console import Console
from rich.table import Table

from lke import __version__
from lke.config import load_settings
from lke.ingest import scan_inbox
from lke.pipeline.stages import run_ingest
from lke.store import Checkpoint, Library

app = typer.Typer(help="Legal Knowledge Extractor")
console = Console()


def open_library() -> Library:
    settings = load_settings()
    settings.ensure_dirs()
    return Library(settings.path("library") / "library.db")


@app.command()
def version():
    """Show the installed version."""
    typer.echo(f"legal-knowledge-extractor {__version__}")


@app.command()
def run():
    """Process all PDFs in the inbox (not implemented yet)."""
    typer.echo("Pipeline not implemented yet.")


@app.command()
def ingest():
    """Stage 1 only: read every PDF in the inbox into work/<doc_id>/pages.jsonl."""
    settings = load_settings()
    settings.ensure_dirs()
    files = scan_inbox(settings.path("inbox"))
    if not files:
        console.print(f"No PDFs found in {settings.path('inbox')}")
        raise typer.Exit()

    table = Table(title=f"Ingest ({len(files)} file(s))")
    for col in ("file", "doc_id", "pages", "ocr", "status", "notes"):
        table.add_column(col)
    with Library(settings.path("library") / "library.db") as lib:
        for path in files:
            console.print(f"Reading {path.name} ...")
            o = run_ingest(path, settings, lib)
            colour = {"done": "green", "skipped": "cyan"}.get(o.status, "red")
            table.add_row(o.filename, o.doc_id, str(o.pages), str(o.ocr_pages),
                          f"[{colour}]{o.status}[/{colour}]", o.message)
    console.print(table)
    console.print(f"Output: {settings.path('work')}")


@app.command()
def status():
    """Show documents, stage progress and record counts."""
    with open_library() as lib:
        docs = lib.list_documents()
        table = Table(title=f"Documents ({len(docs)})")
        for col in ("doc_id", "filename", "pages", "status"):
            table.add_column(col)
        for d in docs:
            table.add_row(d["doc_id"][:12], d["filename"], str(d["page_count"]), d["status"])
        console.print(table)

        stages = Checkpoint(lib).summary()
        if stages:
            st = Table(title="Stages")
            st.add_column("stage")
            st.add_column("done")
            st.add_column("failed")
            st.add_column("running")
            for name, counts in stages.items():
                st.add_row(name, *(str(counts.get(k, 0)) for k in ("done", "failed", "running")))
            console.print(st)

        counts = lib.count_records()
        console.print(f"Records: {sum(counts.values())} {counts if counts else ''}")
        console.print(f"Library: {lib.path}")


@app.command()
def search(query: str, limit: int = 20):
    """Keyword search over the knowledge library."""
    with open_library() as lib:
        hits = lib.search(query, limit)
        if not hits:
            console.print("No results.")
        for h in hits:
            console.print(f"[bold]{h['record_type']}[/bold] {h['title']}  ({h['record_id']})")
            console.print(f"    {h['snippet']}")


if __name__ == "__main__":
    app()
