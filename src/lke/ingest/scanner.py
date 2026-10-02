"""Find PDFs in inbox, compute SHA-256 doc_id."""

from __future__ import annotations

import hashlib
from pathlib import Path


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Hash the file contents in chunks, so even very large PDFs use little memory."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def make_doc_id(path: Path) -> str:
    """Same contents -> same id, even if the file is renamed or moved."""
    return f"doc_{file_sha256(path)[:16]}"


def scan_inbox(inbox: Path) -> list[Path]:
    """All PDFs in the inbox, including sub-folders, in a stable order."""
    if not inbox.exists():
        return []
    return sorted(
        p for p in inbox.rglob("*")
        if p.is_file() and p.suffix.lower() == ".pdf" and not p.name.startswith(".")
    )
