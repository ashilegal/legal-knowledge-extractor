"""Relation (from_id, relation, to_id)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from lke.models.records import Basis


class RelationType(str, Enum):
    PART_OF = "part_of"               # subtopic -> topic, record -> subtopic
    INTERPRETS = "interprets"         # case -> rule/law
    APPLIES = "applies"               # case -> concept/rule
    ESTABLISHES = "establishes"       # case -> principle
    ILLUSTRATES = "illustrates"       # example -> concept/rule
    CITES = "cites"                   # case -> case
    OVERRULES = "overrules"
    DISTINGUISHES = "distinguishes"
    COMPARES = "compares"             # comparison -> concept
    DEFINES = "defines"               # rule -> concept
    RELATED_TO = "related_to"


class Relation(BaseModel):
    from_id: str
    relation: RelationType
    to_id: str
    basis: Basis = Basis.SOURCE
    evidence_ids: list[str] = Field(default_factory=list)
