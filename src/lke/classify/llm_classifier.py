"""Only for unclear sections (cheap model)."""

from __future__ import annotations

from lke.classify.classifier import SectionClass
from lke.classify.rules import CONTENT_TYPES
from lke.config import Settings
from lke.extract.llm_client import JsonLLM
from lke.extract.prompts import load_prompt
from lke.models import Section

PROMPT = "classify_v1"
PREVIEW_CHARS = 6000

SCHEMA = {
    "type": "object",
    "properties": {
        "extract": {"type": "boolean"},
        "types": {"type": "array", "items": {"type": "string", "enum": list(CONTENT_TYPES)}},
        "reason": {"type": "string"},
    },
    "required": ["extract", "types", "reason"],
    "additionalProperties": False,
}


def classify_with_llm(section: Section, current: SectionClass, settings: Settings,
                      llm: JsonLLM) -> SectionClass:
    data = llm.complete_json(
        model=settings.llm.classify_model,
        system=load_prompt(PROMPT, settings.root),
        user=f"Section: {section.title}\n\n<section_text>\n{section.text[:PREVIEW_CHARS]}\n"
             "</section_text>",
        schema=SCHEMA,
        max_tokens=512,
    )
    updated = current.model_copy(update={"method": "llm", "unclear": False})
    if not data["extract"]:
        updated.skip, updated.skip_reason = True, f"LLM: {data['reason']}"
    elif data["types"]:
        updated.types = data["types"]
    return updated
