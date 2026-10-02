"""A stand-in for the Claude API so tests run offline and free."""

from __future__ import annotations

import copy
from typing import Any, Callable

from lke.extract import UsageTracker
from lke.extract.fact_extractor import SCHEMA as FACTS_SCHEMA
from lke.extract.record_composer import SCHEMA as COMPOSE_SCHEMA

Responder = Callable[[str], dict[str, Any]] | dict[str, Any]


class FakeLLM:
    def __init__(self, facts: Responder, compose: Responder | list[Responder]):
        self.facts = facts
        self.compose = compose if isinstance(compose, list) else [compose]
        self.calls: list[dict[str, Any]] = []
        self.usage = UsageTracker()

    def complete_json(self, *, model, system, user, schema, effort=None, max_tokens=None):
        self.calls.append({"model": model, "system": system, "user": user, "schema": schema})
        if schema is FACTS_SCHEMA:
            responder = self.facts
        elif schema is COMPOSE_SCHEMA:
            n = sum(1 for c in self.calls if c["schema"] is COMPOSE_SCHEMA) - 1
            responder = self.compose[min(n, len(self.compose) - 1)]
        else:
            raise AssertionError("unexpected schema")
        return copy.deepcopy(responder(user) if callable(responder) else responder)


CASE_FACTS = {
    "skipped_reason": "",
    "items": [{
        "key": "case-1", "record_type": "CASE", "name": "Shoemaker v. Myers",
        "heading": "Exclusivity",
        "identifiers": [
            {"kind": "case_name", "value": "Shoemaker v. Myers", "role": "", "pages": [3]},
            {"kind": "citation", "value": "(1990) 52 C3d 1", "role": "", "pages": [3]},
            {"kind": "court", "value": "Cal. Supreme Court", "role": "", "pages": [3]},
            {"kind": "date", "value": "1990", "role": "", "pages": [3]},
            {"kind": "provision", "value": "Lab.C. § 3600", "role": "Labor Code", "pages": [3]},
            {"kind": "statute", "value": "Labor Code", "role": "", "pages": [3]},
        ],
        "facts": [
            {"id": "f1", "fact_type": "fact", "note": "employee fired after reporting misconduct",
             "pages": [3], "support": "explicit", "proprietary": False},
            {"id": "f2", "fact_type": "holding", "note": "wrongful termination claim not barred",
             "pages": [3, 99], "support": "explicit", "proprietary": False},
            {"id": "f3", "fact_type": "principle", "note": "exclusivity limited to workplace risks",
             "pages": [4], "support": "inferred", "proprietary": False},
        ],
        "related": [{"name": "workers' compensation exclusivity", "type": "CONCEPT",
                     "relation": "applies"}],
        "proprietary": False, "proprietary_reason": "", "quoted_provision": "",
    }],
}

CASE_COMPOSED = {"records": [{
    "key": "case-1",
    "statements": [
        {"field": "material_facts", "text": "The employee was dismissed after reporting misconduct.",
         "basis": "source", "facts": ["f1"]},
        {"field": "decision", "text": "The wrongful termination claim was allowed to proceed.",
         "basis": "source", "facts": ["f2"]},
        {"field": "principles", "text": "Exclusivity covers only risks inherent in employment.",
         "basis": "source", "facts": ["f3"]},
        {"field": "definition", "text": "Not a CASE field; must be ignored.", "basis": "source",
         "facts": ["f1"]},
    ],
    "comparison_items": [], "concept_illustrated": [],
}]}
