"""Combines both -> content type per span."""

from __future__ import annotations

from pydantic import BaseModel, Field

from lke.classify.rules import CONTENT_TYPES, proprietary_signals, score_text, skip_reason
from lke.models import Section

THRESHOLD = 2.0            # signals per 1000 tokens needed to count a type as present


class SectionClass(BaseModel):
    section_id: str
    types: list[str] = Field(default_factory=list)       # strongest first
    scores: dict[str, float] = Field(default_factory=dict)
    skip: bool = False
    skip_reason: str | None = None
    unclear: bool = False                                # no type reached the threshold
    proprietary_signals: list[str] = Field(default_factory=list)
    method: str = "rules"                                # rules | llm


def classify_section(section: Section) -> SectionClass:
    reason = skip_reason(section.title, section.text, section.token_estimate)
    if reason:
        return SectionClass(section_id=section.section_id, skip=True, skip_reason=reason)
    scores = score_text(section.text, section.token_estimate, section.has_tables)
    types = sorted((t for t in CONTENT_TYPES if scores[t] >= THRESHOLD),
                   key=lambda t: -scores[t])
    return SectionClass(
        section_id=section.section_id,
        types=types or ["CONCEPT"],          # plain explanatory text -> concepts
        scores=scores,
        unclear=not types,
        proprietary_signals=proprietary_signals(section.text),
    )
