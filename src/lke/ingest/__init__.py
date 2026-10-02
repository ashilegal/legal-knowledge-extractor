"""Ingestion."""

from lke.ingest.reader import IngestResult, ingest_pdf
from lke.ingest.scanner import make_doc_id, scan_inbox

__all__ = ["IngestResult", "ingest_pdf", "make_doc_id", "scan_inbox"]
