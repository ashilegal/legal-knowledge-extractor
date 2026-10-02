"""Runs all checks -> pass / regenerate / review."""

from __future__ import annotations

from dataclasses import dataclass, field

from lke.config import ValidationConfig
from lke.extract.fact_extractor import ExtractedItem
from lke.models import AnyRecord, Section
from lke.validate.grounding_check import check_grounding
from lke.validate.overlap_check import SourceIndex, check_overlap
from lke.validate.proprietary_check import check_proprietary
from lke.validate.schema_check import check_schema
from lke.validate.terms_check import check_terms

PASS, REGENERATE, REVIEW = "pass", "regenerate", "review"


@dataclass
class Verdict:
    decision: str
    record: AnyRecord
    too_close: list[str] = field(default_factory=list)


@dataclass
class SectionContext:
    section: Section
    index: SourceIndex
    low_quality_pages: set[int] = field(default_factory=set)

    @classmethod
    def build(cls, section: Section, low_quality_pages: set[int] | None = None):
        return cls(section, SourceIndex(section.text), low_quality_pages or set())


def validate(record: AnyRecord, ctx: SectionContext, item: ExtractedItem | None,
             cfg: ValidationConfig, attempt: int = 0) -> Verdict:
    """Fills record.validation / record.flags and decides what happens next."""
    v = record.validation
    errors: list[str] = []

    schema_errors = check_schema(record)
    grounding_errors, grounding_warnings = check_grounding(record, ctx.section)
    term_errors, term_warnings = check_terms(record, ctx.section.text, item)
    overlap = check_overlap(record, ctx.index)

    v.schema_ok = not schema_errors
    v.grounding_ok = not grounding_errors
    v.terms_ok = not term_errors
    v.overlap_max_run = overlap.max_run
    v.overlap_ratio = overlap.ratio
    v.overlap_ok = overlap.ok(cfg.max_shared_word_run, cfg.max_ngram_overlap)
    errors += schema_errors + grounding_errors + term_errors
    if not v.overlap_ok:
        errors.append(f"wording too close to source (longest shared run {overlap.max_run} "
                      f"words, {overlap.ratio:.0%} of 8-word sequences)")
    v.errors = errors + [f"warning: {w}" for w in grounding_warnings + term_warnings]

    flags = record.flags
    reasons = check_proprietary(record)
    if reasons:
        flags.proprietary = True
    if ctx.low_quality_pages & set(record.pages):
        flags.low_ocr_confidence = True
        reasons.append("based on low-quality OCR pages")

    only_overlap = not (schema_errors or grounding_errors or term_errors) and not v.overlap_ok
    if only_overlap and attempt < cfg.max_regenerate_attempts:
        return Verdict(REGENERATE, record, overlap.phrases)

    review_reasons = errors + reasons
    flags.needs_review = bool(review_reasons)
    flags.reasons = list(dict.fromkeys(flags.reasons + review_reasons))
    return Verdict(REVIEW if flags.needs_review else PASS, record)
