"""PASS 2: facts -> records (never sees source text)."""

from __future__ import annotations

from typing import Any

import regex as re
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from lke.config import Settings
from lke.extract.fact_extractor import ExtractedItem, SectionFacts
from lke.extract.llm_client import JsonLLM
from lke.extract.prompts import load_prompt
from lke.extract.table_extractor import subjects_and_dimensions
from lke.models import AnyRecord, Section, make_id, parse_record
from lke.models.records import Basis, ComparisonItem
from lke.terms import key as term_key
from lke.terms import normalise

PROMPT = "compose_v1"
TYPE_PROMPTS = ["compose_case_v1", "compose_concept_v1", "compose_rule_v1",
                "compose_example_v1", "compose_comparison_v1"]

FIELDS: dict[str, list[str]] = {
    "CASE": ["material_facts", "legal_issues", "decision", "principles", "important_factors"],
    "CONCEPT": ["definition", "key_points", "important_factors"],
    "RULE": ["requirements", "conditions", "exceptions"],
    "EXAMPLE": ["scenario", "important_facts", "result"],
    "COMPARISON": ["key_differences"],
}
SINGLE = {"decision", "definition", "scenario", "result"}      # one statement only
ALL_FIELDS = sorted({f for fields in FIELDS.values() for f in fields})


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


_STR = {"type": "string"}
_IDS = {"type": "array", "items": {"type": "string"}}

SCHEMA = _obj({
    "records": {"type": "array", "items": _obj({
        "key": _STR,
        "statements": {"type": "array", "items": _obj({
            "field": {"type": "string", "enum": ALL_FIELDS},
            "text": _STR,
            "basis": {"type": "string", "enum": ["source", "interpretation"]},
            "facts": _IDS,
        })},
        "comparison_items": {"type": "array", "items": _obj({
            "subject": _STR, "attribute": _STR, "value": _STR, "facts": _IDS,
        })},
        "concept_illustrated": {"type": "array", "items": _STR},
    })},
})


class ComposedStatement(BaseModel):
    field: str
    text: str
    basis: str = "source"
    facts: list[str] = Field(default_factory=list)


class ComposedComparisonItem(BaseModel):
    subject: str
    attribute: str
    value: str
    facts: list[str] = Field(default_factory=list)


class ComposedRecord(BaseModel):
    key: str
    statements: list[ComposedStatement] = Field(default_factory=list)
    comparison_items: list[ComposedComparisonItem] = Field(default_factory=list)
    concept_illustrated: list[str] = Field(default_factory=list)


def system_prompt(settings: Settings) -> str:
    parts = [load_prompt(PROMPT, settings.root)]
    parts += [load_prompt(name, settings.root) for name in TYPE_PROMPTS]
    return "\n\n".join(parts)


def build_request(items: list[ExtractedItem], too_close: dict[str, list[str]] | None = None
                  ) -> str:
    """Only the extracted notes and identifiers go to the composer, never the source text."""
    lines = [
        "For every statement: use only the allowed fields of its item, and in \"facts\" copy "
        "the note ids exactly as shown in square brackets, without the brackets (e.g. \"f1\").",
        "",
    ]
    for item in items:
        lines.append(f"## Item {item.key} ({item.record_type}): {item.name}")
        lines.append(f"Allowed fields: {', '.join(FIELDS[item.record_type])}"
                     + (", comparison_items" if item.record_type == "COMPARISON" else "")
                     + (", concept_illustrated" if item.record_type == "EXAMPLE" else ""))
        exact = [f"{i.kind}: {i.value}" for i in item.identifiers]
        if exact:
            lines.append("Exact terms: " + "; ".join(exact))
        lines.append("Notes:")
        for f in item.facts:
            lines.append(f"- [{f.id}] ({f.fact_type.value}, {f.support}) {f.note}")
        if too_close and too_close.get(item.key):
            lines.append("Phrases too close to the source in the previous attempt "
                         "(reword these points):")
            lines += [f'- "{p}"' for p in too_close[item.key]]
        lines.append("")
    return "\n".join(lines)


def compose_records(items: list[ExtractedItem], settings: Settings, llm: JsonLLM,
                    too_close: dict[str, list[str]] | None = None) -> dict[str, ComposedRecord]:
    if not items:
        return {}
    data = llm.complete_json(
        model=settings.llm.compose_model,
        system=system_prompt(settings),
        user=build_request(items, too_close),
        schema=SCHEMA,
        effort=settings.llm.compose_effort,
    )
    composed = [ComposedRecord(**r) for r in data.get("records", [])]
    return {c.key: c for c in composed}


# ---------- turning notes + composed text into a validated record ----------

def topic_id(name: str) -> str:
    return make_id("top", " ".join(name.lower().split()))


def subtopic_id(topic: str, name: str) -> str:
    return make_id("sub", " ".join(topic.lower().split()), " ".join(name.lower().split()))


def record_id_for(record_type: str, name: str) -> str | None:
    """The library id a CASE / CONCEPT / RULE with this name has (or will have)."""
    if record_type == "CASE":
        return make_id("rec", f"CASE:{term_key('case_name', name)}")
    if record_type in ("CONCEPT", "RULE"):
        return make_id("rec", f"{record_type}:{term_key('statute', name)}")
    return None


def identity_key(item: ExtractedItem, section: Section) -> str:
    """What makes two records 'the same thing' across sections and documents."""
    t = item.record_type
    if t == "CASE":
        case = next((i.value for i in item.identifiers if i.kind == "case_name"), item.name)
        return f"CASE:{term_key('case_name', case)}"
    if t in ("CONCEPT", "RULE"):
        return f"{t}:{term_key('statute', item.name)}"
    return f"{t}:{section.doc_id}:{section.section_id}:{item.key}"     # examples, comparisons


_YEAR = re.compile(r"^\d{4}$")


def _date(value: str) -> dict[str, str]:
    if _YEAR.match(value.strip()):
        return {"value": value.strip(), "precision": "year"}
    return {"value": value.strip(), "precision": "day"}


# Smaller (local) models sometimes use another record type's field name. Instead of
# dropping those points, move them to the closest field of the right type.
FIELD_FALLBACK: dict[str, dict[str, str]] = {
    "CASE": {"definition": "principles", "key_points": "principles",
             "requirements": "principles", "conditions": "important_factors",
             "exceptions": "important_factors", "scenario": "material_facts",
             "important_facts": "material_facts", "result": "decision",
             "key_differences": "important_factors"},
    "CONCEPT": {"principles": "key_points", "requirements": "key_points",
                "conditions": "important_factors", "exceptions": "key_points",
                "material_facts": "key_points", "legal_issues": "key_points",
                "decision": "key_points", "important_facts": "key_points",
                "scenario": "key_points", "result": "key_points",
                "key_differences": "key_points"},
    "RULE": {"definition": "requirements", "key_points": "requirements",
             "principles": "requirements", "material_facts": "conditions",
             "important_factors": "conditions", "legal_issues": "conditions",
             "decision": "requirements", "important_facts": "conditions",
             "scenario": "conditions", "result": "requirements",
             "key_differences": "requirements"},
    "EXAMPLE": {"material_facts": "important_facts", "key_points": "important_facts",
                "decision": "result", "principles": "important_facts",
                "requirements": "important_facts", "conditions": "important_facts"},
    "COMPARISON": {"key_points": "key_differences", "principles": "key_differences",
                   "requirements": "key_differences", "important_factors": "key_differences"},
}
MATCH_SCORE = 60          # similarity needed to link a statement to a note automatically
_ID_JUNK = re.compile(r"[\s\[\]()#\"'`]")


def _normalise_id(value: str) -> str:
    return _ID_JUNK.sub("", value).lower()


def build_record(section: Section, item: ExtractedItem, composed: ComposedRecord | None,
                 settings: Settings, model_info: str) -> AnyRecord:
    """Combine pass-1 identifiers (exact) with pass-2 statements (own wording)."""
    valid_pages = set(range(section.page_start, section.page_end + 1))
    facts = {f.id: f for f in item.facts}
    order = [f.id for f in item.facts]
    lookup: dict[str, str] = {}
    for n, fid in enumerate(order, 1):
        norm = _normalise_id(fid)
        for alias in (norm, norm.split("-")[-1], str(n), f"f{n}", f"note{n}"):
            lookup.setdefault(alias, fid)

    used: list[str] = []

    def resolve(cited: list[str], text: str) -> list[str]:
        """Note ids cited by the model; if none are usable, the most similar notes."""
        ids = [lookup[_normalise_id(c)] for c in cited if _normalise_id(c) in lookup]
        if not ids and text:
            scored = sorted(((fuzz.token_set_ratio(text.lower(), facts[f].note.lower()), f)
                             for f in order), reverse=True)
            ids = [f for score, f in scored[:2] if score >= MATCH_SCORE]
        return list(dict.fromkeys(ids))

    def evidence_ids(ids: list[str]) -> list[str]:
        for fid in ids:
            if fid not in used:
                used.append(fid)
        return [f"{section.section_id}:{fid}" for fid in ids]

    statements: dict[str, list[dict]] = {}
    comparison_items: list[dict] = []
    illustrated: list[str] = []
    allowed = FIELDS[item.record_type]
    fallback = FIELD_FALLBACK.get(item.record_type, {})
    if composed:
        for st in composed.statements:
            field = st.field if st.field in allowed else fallback.get(st.field)
            if field not in allowed or not st.text.strip():
                continue
            ids = resolve(st.facts, st.text)
            inferred = any(facts[f].support == "inferred" for f in ids)
            basis = Basis.INTERPRETATION.value if inferred else st.basis
            statements.setdefault(field, []).append(
                {"text": st.text.strip(), "basis": basis, "evidence": evidence_ids(ids)})
        for ci in composed.comparison_items:
            ids = resolve(ci.facts, f"{ci.subject} {ci.attribute} {ci.value}")
            comparison_items.append({"subject": ci.subject, "attribute": ci.attribute,
                                     "value": ci.value, "evidence": evidence_ids(ids)})
        illustrated = [c for c in composed.concept_illustrated if c.strip()]

    evidence = []
    for fid in used or [f.id for f in item.facts]:
        pages = sorted(p for p in facts[fid].pages if p in valid_pages) or [section.page_start]
        evidence.append({"id": f"{section.section_id}:{fid}", "doc_id": section.doc_id,
                         "pages": pages})

    def ids_of(kind: str) -> list[str]:
        return [i.value for i in item.identifiers if i.kind == kind]

    fields: dict[str, Any] = {}
    for name in FIELDS[item.record_type]:
        values = statements.get(name, [])
        fields[name] = (values[0] if values else None) if name in SINGLE else values
    related = [{"name": r.name, "type": r.type, "relation": r.relation} for r in item.related]
    fields["related"] = related

    laws = []
    statutes = ids_of("statute")
    for ident in item.identifiers:
        if ident.kind == "provision":
            laws.append({"statute": ident.role or (statutes[0] if len(statutes) == 1 else ""),
                         "provision": normalise("provision", ident.value)})
    covered = {term_key("statute", l["statute"]) for l in laws}
    for s in statutes:
        if term_key("statute", s) not in covered:
            laws.append({"statute": s, "provision": ""})

    t = item.record_type
    if t == "CASE":
        fields["case_name"] = normalise("case_name", (ids_of("case_name") or [item.name])[0])
        fields["citation"] = "; ".join(dict.fromkeys(ids_of("citation"))) or None
        fields["court"] = (ids_of("court") or [None])[0]
        dates = ids_of("date")
        fields["date"] = _date(dates[0]) if dates else None
        fields["parties"] = [{"name": i.value, "role": i.role} for i in item.identifiers
                             if i.kind == "party"]
        fields["laws"] = laws
    elif t == "CONCEPT":
        fields["concept_name"] = item.name
    elif t == "RULE":
        quote = item.quoted_provision.strip()
        v = settings.validation
        if laws and quote and v.allow_statute_quotes and len(quote.split()) <= v.max_quote_words:
            laws[0]["quoted_provision"] = quote
        fields["rule_name"] = item.name
        fields["provisions"] = laws
    elif t == "EXAMPLE":
        fields["concept_illustrated"] = illustrated
        if fields.get("scenario") is None:            # scenario is required for examples
            fields["scenario"] = {"text": item.name, "basis": "interpretation",
                                  "evidence": [evidence[0]["id"]] if evidence else []}
    elif t == "COMPARISON":
        items_models = [ComparisonItem(**c) for c in comparison_items]
        subjects, dimensions = subjects_and_dimensions(items_models)
        fields.update({"title": item.name, "subjects": subjects if len(subjects) >= 2
                       else (subjects + ["(unspecified)"] * (2 - len(subjects))),
                       "dimensions": dimensions, "items": comparison_items})

    topic_name = section.topic_path[0] if section.topic_path else None
    sub_name = section.topic_path[1] if len(section.topic_path) > 1 else (item.heading or None)
    reasons = [item.proprietary_reason] if item.proprietary and item.proprietary_reason else []
    proprietary_notes = [f.id for f in item.facts if f.proprietary]
    if proprietary_notes:
        reasons.append(f"author commentary in notes {', '.join(proprietary_notes)}")

    data = {
        "record_type": t,
        "record_id": make_id("rec", identity_key(item, section)),
        "topic": {"id": topic_id(topic_name), "name": topic_name} if topic_name else None,
        "subtopic": ({"id": subtopic_id(topic_name or "", sub_name), "name": sub_name}
                     if sub_name else None),
        "evidence": evidence,
        "fields": fields,
        "flags": {"proprietary": item.proprietary or bool(proprietary_notes),
                  "reasons": reasons},
        "provenance": {"prompt_version": f"{PROMPT}+extract_facts_v1", "model": model_info},
    }
    return parse_record(data)


def build_record_pairs(section: Section, facts: SectionFacts,
                       composed: dict[str, ComposedRecord], settings: Settings
                       ) -> tuple[list[tuple[ExtractedItem, AnyRecord]], list[str]]:
    """Returns ([(item, record)], errors). An item that cannot form a valid record is
    reported in errors instead of stopping the section."""
    pairs, errors = [], []
    model_info = f"{facts.model} / {settings.llm.compose_model}"
    for item in facts.items:
        try:
            pairs.append((item, build_record(section, item, composed.get(item.key), settings,
                                             model_info)))
        except Exception as e:
            errors.append(f"{item.key} ({item.record_type} '{item.name}'): {e}")
    return pairs, errors


def build_records(section: Section, facts: SectionFacts,
                  composed: dict[str, ComposedRecord], settings: Settings
                  ) -> tuple[list[AnyRecord], list[str]]:
    pairs, errors = build_record_pairs(section, facts, composed, settings)
    return [record for _, record in pairs], errors
