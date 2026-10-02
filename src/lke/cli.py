import typer

from lke import __version__

app = typer.Typer(help="Legal Knowledge Extractor")


@app.command()
def version():
    """Show the installed version."""
    typer.echo(f"legal-knowledge-extractor {__version__}")


@app.command()
def run():
    """Process all PDFs in the inbox (not implemented yet)."""
    typer.echo("Pipeline not implemented yet.")


if __name__ == "__main__":
    app()
