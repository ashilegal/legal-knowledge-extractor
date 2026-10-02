"""Fact (text, type, page, char_span, support)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class FactType(str, Enum):
    FACT = "fact"                     # material / factual information
    ISSUE = "issue"
    HOLDING = "holding"               # decision / outcome
    PRINCIPLE = "principle"
    DEFINITION = "definition"
    REQUIREMENT = "requirement"
    CONDITION = "condition"
    EXCEPTION = "exception"
    FACTOR = "factor"
    SCENARIO = "scenario"
    RESULT = "result"
    ATTRIBUTE = "attribute"           # one cell/relationship from a table or comparison
    METADATA = "metadata"             # case name, court, date, parties, provision ...


class Support(str, Enum):
    EXPLICIT = "explicit"             # stated in the source
    INFERRED = "inferred"             # model's interpretation


class Evidence(BaseModel):
    """Where in the source a statement comes from. Stores location, never copied text."""

    doc_id: str
    pages: list[int] = Field(min_length=1)
    char_span: tuple[int, int] | None = None

    @model_validator(mode="after")
    def _check_span(self) -> "Evidence":
        if self.char_span and self.char_span[0] > self.char_span[1]:
            raise ValueError("char_span start must be <= end")
        return self


class Fact(BaseModel):
    fact_id: str
    section_id: str
    fact_type: FactType
    text: str = Field(min_length=1)
    support: Support = Support.EXPLICIT
    evidence: Evidence
    protected_terms: list[str] = Field(default_factory=list)
    proprietary: bool = False         # firm commentary, unique example, distinctive table
