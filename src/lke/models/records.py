"""BaseRecord + CaseRecord, ConceptRecord, RuleRecord, ExampleRecord, ComparisonRecord."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Iterator, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, model_validator

SCHEMA_VERSION = "1.0"


class Basis(str, Enum):
    SOURCE = "source"                 # supported by the source document
    INTERPRETATION = "interpretation" # generated interpretation


class Statement(BaseModel):
    """One independently worded point, tied to evidence."""

    text: str = Field(min_length=1)
    basis: Basis = Basis.SOURCE
    evidence: list[str] = Field(default_factory=list)   # evidence ids


class EvidenceRef(BaseModel):
    id: str
    doc_id: str
    pages: list[int] = Field(min_length=1)
    char_span: tuple[int, int] | None = None


class TopicRef(BaseModel):
    id: str
    name: str


class DateValue(BaseModel):
    value: str                        # "1978", "1978-03-21"
    precision: Literal["year", "month", "day"] = "year"


class Party(BaseModel):
    name: str
    role: str = ""                    # appellant, respondent, petitioner ...


class LawRef(BaseModel):
    statute: str                      # exact name, e.g. "Industrial Disputes Act, 1947"
    provision: str = ""               # exact number, e.g. "Section 25F"
    entity_id: str | None = None
    quoted_provision: str | None = None   # short exact quote, clearly marked


class RelatedRef(BaseModel):
    name: str
    type: str = ""                    # CASE, CONCEPT, RULE ...
    record_id: str | None = None
    relation: str = "related_to"


class Flags(BaseModel):
    proprietary: bool = False
    low_ocr_confidence: bool = False
    needs_review: bool = False
    reasons: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    schema_ok: bool | None = None
    grounding_ok: bool | None = None
    terms_ok: bool | None = None
    overlap_ok: bool | None = None
    overlap_max_run: int | None = None
    overlap_ratio: float | None = None
    errors: list[str] = Field(default_factory=list)


class Provenance(BaseModel):
    extractor_version: str = "0.1.0"
    prompt_version: str = ""
    model: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------- type-specific fields ----------

class CaseFields(BaseModel):
    case_name: str
    citation: str | None = None
    court: str | None = None
    date: DateValue | None = None
    parties: list[Party] = Field(default_factory=list)
    material_facts: list[Statement] = Field(default_factory=list)
    legal_issues: list[Statement] = Field(default_factory=list)
    laws: list[LawRef] = Field(default_factory=list)
    decision: Statement | None = None
    principles: list[Statement] = Field(default_factory=list)
    important_factors: list[Statement] = Field(default_factory=list)
    related: list[RelatedRef] = Field(default_factory=list)


class ConceptFields(BaseModel):
    concept_name: str
    definition: Statement | None = None
    key_points: list[Statement] = Field(default_factory=list)
    important_factors: list[Statement] = Field(default_factory=list)
    related: list[RelatedRef] = Field(default_factory=list)


class RuleFields(BaseModel):
    rule_name: str
    provisions: list[LawRef] = Field(default_factory=list)
    requirements: list[Statement] = Field(default_factory=list)
    conditions: list[Statement] = Field(default_factory=list)
    exceptions: list[Statement] = Field(default_factory=list)
    related: list[RelatedRef] = Field(default_factory=list)


class ExampleFields(BaseModel):
    scenario: Statement
    concept_illustrated: list[str] = Field(default_factory=list)
    important_facts: list[Statement] = Field(default_factory=list)
    result: Statement | None = None
    related: list[RelatedRef] = Field(default_factory=list)


class ComparisonItem(BaseModel):
    subject: str                      # e.g. "CGL insurance"
    attribute: str                    # e.g. "covers administrative errors"
    value: str                        # e.g. "no"
    basis: Basis = Basis.SOURCE
    evidence: list[str] = Field(default_factory=list)


class ComparisonFields(BaseModel):
    title: str
    subjects: list[str] = Field(min_length=2)
    dimensions: list[str] = Field(default_factory=list)
    items: list[ComparisonItem] = Field(default_factory=list)
    key_differences: list[Statement] = Field(default_factory=list)
    related: list[RelatedRef] = Field(default_factory=list)


# ---------- record envelope ----------

class BaseRecord(BaseModel):
    record_id: str
    schema_version: str = SCHEMA_VERSION
    topic: TopicRef | None = None
    subtopic: TopicRef | None = None
    evidence: list[EvidenceRef] = Field(min_length=1)
    flags: Flags = Field(default_factory=Flags)
    validation: ValidationResult = Field(default_factory=ValidationResult)
    provenance: Provenance = Field(default_factory=Provenance)

    def statements(self) -> Iterator[Statement | ComparisonItem]:
        yield from _iter_statements(getattr(self, "fields", None))

    @property
    def doc_ids(self) -> set[str]:
        return {e.doc_id for e in self.evidence}

    @property
    def pages(self) -> list[int]:
        return sorted({p for e in self.evidence for p in e.pages})

    @model_validator(mode="after")
    def _evidence_ids_exist(self) -> "BaseRecord":
        known = {e.id for e in self.evidence}
        for st in self.statements():
            missing = [eid for eid in st.evidence if eid not in known]
            if missing:
                raise ValueError(f"statement refers to unknown evidence ids: {missing}")
        return self


class CaseRecord(BaseRecord):
    record_type: Literal["CASE"] = "CASE"
    fields: CaseFields


class ConceptRecord(BaseRecord):
    record_type: Literal["CONCEPT"] = "CONCEPT"
    fields: ConceptFields


class RuleRecord(BaseRecord):
    record_type: Literal["RULE"] = "RULE"
    fields: RuleFields


class ExampleRecord(BaseRecord):
    record_type: Literal["EXAMPLE"] = "EXAMPLE"
    fields: ExampleFields


class ComparisonRecord(BaseRecord):
    record_type: Literal["COMPARISON"] = "COMPARISON"
    fields: ComparisonFields


AnyRecord = Annotated[
    Union[CaseRecord, ConceptRecord, RuleRecord, ExampleRecord, ComparisonRecord],
    Field(discriminator="record_type"),
]

_record_adapter: TypeAdapter[AnyRecord] = TypeAdapter(AnyRecord)


def parse_record(data: dict[str, Any] | str) -> AnyRecord:
    """Parse a dict or JSON string into the correct record class."""
    if isinstance(data, str):
        return _record_adapter.validate_json(data)
    return _record_adapter.validate_python(data)


def _iter_statements(obj: Any) -> Iterator[Statement | ComparisonItem]:
    if isinstance(obj, (Statement, ComparisonItem)):
        yield obj
    elif isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            yield from _iter_statements(getattr(obj, name))
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_statements(item)
