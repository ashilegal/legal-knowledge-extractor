"""PASS 1: section -> facts with page refs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from lke.config import Settings
from lke.extract.llm_client import JsonLLM
from lke.extract.prompts import load_prompt
from lke.models import FactType, Section
from lke.terms import ProtectedTerms

PROMPT = "extract_facts_v1"
RECORD_TYPES = ["CASE", "CONCEPT", "RULE", "EXAMPLE", "COMPARISON"]
IDENTIFIER_KINDS = ["case_name", "citation", "court", "date", "party", "statute", "provision",
                    "defined_term"]
RELATIONS = ["cites", "applies", "interprets", "establishes", "illustrates", "distinguishes",
             "overrules", "compares", "defines", "related_to"]


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


_STR = {"type": "string"}
_PAGES = {"type": "array", "items": {"type": "integer"}}

SCHEMA = _obj({
    "items": {"type": "array", "items": _obj({
        "key": _STR,
        "record_type": {"type": "string", "enum": RECORD_TYPES},
        "name": _STR,
        "heading": _STR,
        "identifiers": {"type": "array", "items": _obj({
            "kind": {"type": "string", "enum": IDENTIFIER_KINDS},
            "value": _STR, "role": _STR, "pages": _PAGES,
        })},
        "facts": {"type": "array", "items": _obj({
            "id": _STR,
            "fact_type": {"type": "string", "enum": [t.value for t in FactType]},
            "note": _STR,
            "pages": _PAGES,
            "support": {"type": "string", "enum": ["explicit", "inferred"]},
            "proprietary": {"type": "boolean"},
        })},
        "related": {"type": "array", "items": _obj({
            "name": _STR,
            "type": {"type": "string", "enum": ["CASE", "CONCEPT", "RULE", "STATUTE"]},
            "relation": {"type": "string", "enum": RELATIONS},
        })},
        "proprietary": {"type": "boolean"},
        "proprietary_reason": _STR,
        "quoted_provision": _STR,
    })},
    "skipped_reason": _STR,
})


# ---------- parsed output ----------

class Identifier(BaseModel):
    kind: str
    value: str
    role: str = ""
    pages: list[int] = Field(default_factory=list)


class ExtractedFact(BaseModel):
    id: str
    fact_type: FactType
    note: str
    pages: list[int] = Field(default_factory=list)
    support: str = "explicit"
    proprietary: bool = False


class RelatedName(BaseModel):
    name: str
    type: str
    relation: str = "related_to"


class ExtractedItem(BaseModel):
    key: str
    record_type: str
    name: str
    heading: str = ""
    identifiers: list[Identifier] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    related: list[RelatedName] = Field(default_factory=list)
    proprietary: bool = False
    proprietary_reason: str = ""
    quoted_provision: str = ""


class SectionFacts(BaseModel):
    section_id: str
    items: list[ExtractedItem] = Field(default_factory=list)
    skipped_reason: str = ""
    model: str = ""
    prompt_version: str = PROMPT


def build_request(section: Section, terms: ProtectedTerms, type_hints: list[str],
                  settings: Settings) -> str:
    v = settings.validation
    quotes = (f"allowed, at most {v.max_quote_words} words" if v.allow_statute_quotes
              else "not allowed: always return \"\"")
    return "\n".join([
        f"Document section: {section.title}",
        f"Topic path: {' > '.join(section.topic_path) or '(none)'}",
        f"Pages: {section.page_start}-{section.page_end}",
        f"Likely content types (from keyword rules, may be incomplete): {', '.join(type_hints)}",
        f"Statutory quotes: {quotes}",
        "",
        "Identifiers detected in this section (keep these exactly as written):",
        terms.as_prompt_list(),
        "",
        "<section_text>",
        section.text,
        "</section_text>",
    ])


def _unique_fact_ids(items: list[ExtractedItem]) -> None:
    """Fact ids must be unique across the whole section."""
    seen: set[str] = set()
    for item in items:
        for n, fact in enumerate(item.facts, 1):
            fid = fact.id.strip() or f"{item.key}-f{n}"
            if fid in seen:
                fid = f"{item.key}-{fid}"
            seen.add(fid)
            fact.id = fid


def extract_facts(section: Section, terms: ProtectedTerms, type_hints: list[str],
                  settings: Settings, llm: JsonLLM) -> SectionFacts:
    model = settings.llm.extract_model
    data = llm.complete_json(
        model=model,
        system=load_prompt(PROMPT, settings.root),
        user=build_request(section, terms, type_hints, settings),
        schema=SCHEMA,
        effort=settings.llm.extract_effort,
    )
    result = SectionFacts(section_id=section.section_id, model=model, **data)
    result.items = [i for i in result.items if i.record_type in RECORD_TYPES and i.facts]
    keys: set[str] = set()
    for n, item in enumerate(result.items, 1):          # keys must be unique too
        if item.key in keys or not item.key.strip():
            item.key = f"{item.record_type.lower()}-{n}"
        keys.add(item.key)
    _unique_fact_ids(result.items)
    return result
