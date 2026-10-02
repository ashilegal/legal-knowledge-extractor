import copy

from lke.config import Settings, ValidationConfig
from lke.extract import build_records, compose_records, extract_facts
from lke.models import Section
from lke.terms import protected_terms
from lke.validate import PASS, REGENERATE, REVIEW, SectionContext, SourceIndex, check_overlap, validate
from tests.fakes import CASE_COMPOSED, CASE_FACTS, FakeLLM

SOURCE = (
    "[[p. 3]]\nIn Shoemaker v. Myers (1990) 52 C3d 1 the Cal. Supreme Court considered an "
    "employee who was dismissed for reporting misconduct to his superiors and who then sued "
    "for wrongful termination in violation of public policy under the Labor Code, "
    "Lab.C. § 3600.\n[[p. 4]]\nThe court allowed the claim to proceed."
)


def build(composed=CASE_COMPOSED, facts=CASE_FACTS):
    settings = Settings()
    section = Section(section_id="sec_1", doc_id="doc_1", title="Exclusivity",
                      topic_path=["Workers' Compensation", "Exclusivity"],
                      page_start=3, page_end=4, text=SOURCE, token_estimate=80)
    llm = FakeLLM(facts, composed)
    f = extract_facts(section, protected_terms(SOURCE), ["CASE"], settings, llm)
    records, errors = build_records(section, f, compose_records(f.items, settings, llm),
                                    settings)
    assert not errors
    return section, f.items[0], records[0]


def test_clean_record_passes():
    section, item, record = build()
    verdict = validate(record, SectionContext.build(section), item, ValidationConfig())
    assert verdict.decision == PASS, record.validation.errors
    assert record.validation.overlap_ok and record.validation.terms_ok
    assert not record.flags.needs_review


def test_copied_wording_triggers_regenerate_then_review():
    composed = copy.deepcopy(CASE_COMPOSED)
    composed["records"][0]["statements"][0]["text"] = (
        "An employee who was dismissed for reporting misconduct to his superiors and who "
        "then sued for wrongful termination.")
    section, item, record = build(composed)
    ctx = SectionContext.build(section)
    first = validate(record, ctx, item, ValidationConfig(), attempt=0)
    assert first.decision == REGENERATE
    assert any("reporting misconduct to his superiors" in p for p in first.too_close)
    second = validate(record, ctx, item, ValidationConfig(), attempt=1)
    assert second.decision == REVIEW
    assert record.flags.needs_review
    assert any("too close" in r for r in record.flags.reasons)


def test_identifiers_do_not_count_as_copying():
    index = SourceIndex("Section 25F of the Industrial Disputes Act, 1947 applies to the "
                        "Workmen of Meenakshi Mills Ltd. v. Meenakshi Mills Ltd. dispute.")
    _, _, record = build()
    record.fields.material_facts[0].text = (
        "Workmen of Meenakshi Mills Ltd. v. Meenakshi Mills Ltd. turned on Section 25F of the "
        "Industrial Disputes Act, 1947.")
    assert check_overlap(record, index).max_run < 6


def test_invented_citation_goes_to_review():
    facts = copy.deepcopy(CASE_FACTS)
    facts["items"][0]["identifiers"].append(
        {"kind": "citation", "value": "(2099) 1 SCC 999", "role": "", "pages": [3]})
    section, item, record = build(facts=facts)
    verdict = validate(record, SectionContext.build(section), item, ValidationConfig())
    assert verdict.decision == REVIEW
    assert not record.validation.terms_ok
    assert any("(2099) 1 SCC 999" in e for e in record.validation.errors)


def test_unsupported_source_statement_goes_to_review():
    composed = copy.deepcopy(CASE_COMPOSED)
    composed["records"][0]["statements"][1]["facts"] = ["no-such-note"]
    section, item, record = build(composed)
    verdict = validate(record, SectionContext.build(section), item, ValidationConfig())
    assert verdict.decision == REVIEW and not record.validation.grounding_ok


def test_author_voice_and_low_ocr_are_flagged():
    composed = copy.deepcopy(CASE_COMPOSED)
    composed["records"][0]["statements"][0]["text"] = "We recommend settling such claims early."
    section, item, record = build(composed)
    ctx = SectionContext.build(section, low_quality_pages={3})
    verdict = validate(record, ctx, item, ValidationConfig())
    assert verdict.decision == REVIEW
    assert record.flags.proprietary and record.flags.low_ocr_confidence
