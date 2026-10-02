"""Data shapes (pydantic)."""

import hashlib

from lke.models.document import Document, DocumentStatus, Page, Section, TextLine
from lke.models.facts import Evidence, Fact, FactType, Support
from lke.models.records import (
    AnyRecord,
    Basis,
    CaseRecord,
    ComparisonRecord,
    ConceptRecord,
    EvidenceRef,
    ExampleRecord,
    RuleRecord,
    Statement,
    parse_record,
)
from lke.models.relations import Relation, RelationType


def make_id(prefix: str, *parts: object, length: int = 16) -> str:
    """Stable ID from its parts, so re-running a stage gives the same IDs."""
    raw = "|".join(str(p) for p in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:length]}"


__all__ = [
    "AnyRecord", "Basis", "CaseRecord", "ComparisonRecord", "ConceptRecord",
    "Document", "DocumentStatus", "Evidence", "EvidenceRef", "ExampleRecord",
    "Fact", "FactType", "Page", "Relation", "RelationType", "RuleRecord",
    "Section", "Statement", "Support", "TextLine", "make_id", "parse_record",
]
