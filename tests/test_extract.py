from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from lke.config import LlmConfig, Settings
from lke.extract import (
    AnthropicLLM,
    LLMRefusal,
    LLMTruncated,
    build_records,
    compose_records,
    extract_facts,
)
from lke.extract.llm_client import FALLBACK_BETA
from lke.models import CaseRecord, Section
from lke.models.records import Basis
from lke.terms import protected_terms
from tests.fakes import CASE_COMPOSED, CASE_FACTS, FakeLLM

SOURCE = ("[[p. 3]]\nIn Shoemaker v. Myers (1990) 52 C3d 1 the Cal. Supreme Court held a "
          "distinctive sentence that must never reach the composer.\n[[p. 4]]\nMore text.")


def make_section() -> Section:
    return Section(section_id="sec_1", doc_id="doc_1", title="Exclusivity",
                   topic_path=["Workers' Compensation", "Exclusivity"],
                   page_start=3, page_end=4, text=SOURCE, token_estimate=60)


def run_pipeline(settings: Settings, llm: FakeLLM):
    section = make_section()
    facts = extract_facts(section, protected_terms(section.text), ["CASE"], settings, llm)
    composed = compose_records(facts.items, settings, llm)
    return section, facts, build_records(section, facts, composed, settings)


def test_two_pass_extraction_builds_grounded_case(tmp_path):
    settings = Settings(root=tmp_path)
    llm = FakeLLM(CASE_FACTS, CASE_COMPOSED)
    section, facts, (records, errors) = run_pipeline(settings, llm)
    assert errors == []
    record = records[0]
    assert isinstance(record, CaseRecord)
    f = record.fields
    assert f.case_name == "Shoemaker v. Myers"                 # identifiers copied exactly
    assert f.citation == "(1990) 52 C3d 1"
    assert f.court == "Cal. Supreme Court"
    assert f.date.precision == "year"
    assert f.laws[0].provision == "Lab.C. § 3600" and f.laws[0].statute == "Labor Code"
    assert f.decision.text.startswith("The wrongful termination claim")
    assert f.principles[0].basis == Basis.INTERPRETATION       # built on an inferred note
    assert record.topic.name == "Workers' Compensation"
    assert record.subtopic.name == "Exclusivity"
    assert record.pages == [3, 4]                               # page 99 is outside the section
    assert {e.doc_id for e in record.evidence} == {"doc_1"}


def test_composer_never_sees_source_text(tmp_path):
    settings = Settings(root=tmp_path)
    llm = FakeLLM(CASE_FACTS, CASE_COMPOSED)
    run_pipeline(settings, llm)
    extract_call, compose_call = llm.calls
    assert "distinctive sentence" in extract_call["user"]
    assert "distinctive sentence" not in compose_call["user"]
    assert "<section_text>" not in compose_call["user"]
    assert "[f1]" in compose_call["user"]                       # notes are passed instead
    assert "Lab.C. § 3600" in compose_call["user"]              # with the exact terms


def test_same_case_gets_same_record_id_everywhere(tmp_path):
    settings = Settings(root=tmp_path)
    _, _, (first, _) = run_pipeline(settings, FakeLLM(CASE_FACTS, CASE_COMPOSED))
    other = dict(CASE_FACTS)
    other["items"] = [dict(CASE_FACTS["items"][0], name="Shoemaker vs Myers")]
    other["items"][0]["identifiers"] = [{"kind": "case_name", "value": "Shoemaker vs. Myers",
                                         "role": "", "pages": [3]}]
    _, _, (second, _) = run_pipeline(settings, FakeLLM(other, CASE_COMPOSED))
    assert first[0].record_id == second[0].record_id


# ---------- the real client, with the network replaced ----------

def fake_response(stop_reason="end_turn", text='{"ok": true}'):
    return SimpleNamespace(
        stop_reason=stop_reason, stop_details=SimpleNamespace(category="cyber"),
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
    )


class FakeMessages:
    def __init__(self, responses, error=None):
        self.responses = list(responses)
        self.error = error
        self.calls = []

    def create(self, **params):
        self.calls.append(params)
        if self.error and "fallbacks" in params:
            raise self.error
        return self.responses.pop(0)


def fake_client(responses, beta_error=None):
    beta = FakeMessages(responses, beta_error)
    plain = FakeMessages(responses)
    return SimpleNamespace(messages=plain, beta=SimpleNamespace(messages=beta)), beta, plain


def call(llm, model="claude-opus-5-5"):
    return llm.complete_json(model=model, system="rules", user="text",
                             schema={"type": "object"}, effort="medium")


def test_client_request_shape_and_cost():
    client, beta, _ = fake_client([fake_response()])
    llm = AnthropicLLM(LlmConfig(), client=client)
    assert call(llm) == {"ok": True}
    params = beta.calls[0]
    assert params["output_config"] == {"format": {"type": "json_schema",
                                                  "schema": {"type": "object"}},
                                       "effort": "medium"}
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["betas"] == [FALLBACK_BETA] and params["fallbacks"] == "default"
    assert llm.usage.cost(LlmConfig().prices_per_million) == pytest.approx(0.008)


def test_haiku_gets_no_effort_and_no_fallback():
    client, beta, plain = fake_client([fake_response()])
    call(AnthropicLLM(LlmConfig(), client=client), model="claude-haiku-4-5")
    assert not beta.calls
    assert "effort" not in plain.calls[0]["output_config"]


def test_refusal_and_truncation_raise():
    client, _, _ = fake_client([fake_response("refusal"), fake_response("max_tokens")])
    llm = AnthropicLLM(LlmConfig(), client=client)
    with pytest.raises(LLMRefusal):
        call(llm)
    with pytest.raises(LLMTruncated):
        call(llm)


def test_fallback_switched_off_when_not_available():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.BadRequestError("fallbacks not supported",
                                      response=httpx2.Response(400, request=request), body=None)
    client, beta, plain = fake_client([fake_response(), fake_response()], beta_error=error)
    llm = AnthropicLLM(LlmConfig(), client=client)
    call(llm)
    call(llm)
    assert len(beta.calls) == 1 and len(plain.calls) == 2      # tried once, then plain calls


def test_example_comparison_and_rule_records(tmp_path):
    settings = Settings(root=tmp_path)
    fact = lambda fid, t="fact": {"id": fid, "fact_type": t, "note": "note " + fid, "pages": [3],
                                  "support": "explicit", "proprietary": False}
    item = lambda key, rtype, name, facts, **extra: {
        "key": key, "record_type": rtype, "name": name, "heading": "", "identifiers": [],
        "facts": facts, "related": [], "proprietary": False, "proprietary_reason": "",
        "quoted_provision": "", **extra}
    facts = {"skipped_reason": "", "items": [
        item("ex-1", "EXAMPLE", "Delivery driver injured", [fact("e1", "scenario")],
             proprietary=True, proprietary_reason="author's own hypothetical"),
        item("cmp-1", "COMPARISON", "EBL vs CGL", [fact("c1", "attribute"), fact("c2", "attribute")]),
        item("rule-1", "RULE", "Notice before retrenchment", [fact("r1", "requirement")],
             identifiers=[{"kind": "provision", "value": "S. 25-F", "role": "Industrial Disputes Act, 1947",
                           "pages": [3]}],
             quoted_provision="No workman shall be retrenched until"),
    ]}
    composed = {"records": [
        {"key": "ex-1", "statements": [
            {"field": "scenario", "text": "A driver is hurt on a delivery.", "basis": "source",
             "facts": ["e1"]}], "comparison_items": [], "concept_illustrated": ["course of employment"]},
        {"key": "cmp-1", "statements": [], "concept_illustrated": [], "comparison_items": [
            {"subject": "EBL", "attribute": "administrative errors", "value": "covered", "facts": ["c1"]},
            {"subject": "CGL", "attribute": "administrative errors", "value": "excluded", "facts": ["c2"]}]},
        {"key": "rule-1", "statements": [
            {"field": "requirements", "text": "Notice is required.", "basis": "source",
             "facts": ["r1"]}], "comparison_items": [], "concept_illustrated": []},
    ]}
    section = make_section()
    llm = FakeLLM(facts, composed)
    f = extract_facts(section, protected_terms(section.text), [], settings, llm)
    records, errors = build_records(section, f, compose_records(f.items, settings, llm), settings)
    assert errors == []
    example, comparison, rule = records
    assert example.flags.proprietary and example.fields.concept_illustrated == ["course of employment"]
    assert comparison.fields.subjects == ["EBL", "CGL"]
    assert comparison.fields.dimensions == ["administrative errors"]
    assert rule.fields.provisions[0].provision == "Section 25F"
    assert rule.fields.provisions[0].statute == "Industrial Disputes Act, 1947"
    assert rule.fields.provisions[0].quoted_provision == "No workman shall be retrenched until"
