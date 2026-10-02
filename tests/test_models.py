import pytest
from pydantic import ValidationError

from lke.config import load_settings
from lke.models import CaseRecord, make_id, parse_record


def sample_case() -> dict:
    return {
        "record_type": "CASE",
        "record_id": make_id("rec", "doc1", "sec1", "case1"),
        "topic": {"id": "top_employment", "name": "Employment Law"},
        "subtopic": {"id": "sub_retrenchment", "name": "Retrenchment"},
        "evidence": [{"id": "ev1", "doc_id": "doc1", "pages": [212, 213]}],
        "fields": {
            "case_name": "Example Ltd v. Workers Union",
            "court": "Supreme Court of India",
            "date": {"value": "1978", "precision": "year"},
            "laws": [{"statute": "Industrial Disputes Act, 1947", "provision": "Section 25F"}],
            "material_facts": [{"text": "Workers were retrenched without notice.", "evidence": ["ev1"]}],
            "decision": {"text": "Retrenchment held invalid.", "evidence": ["ev1"]},
        },
    }


def test_parse_case_record():
    record = parse_record(sample_case())
    assert isinstance(record, CaseRecord)
    assert record.pages == [212, 213]
    assert record.fields.laws[0].provision == "Section 25F"


def test_unknown_evidence_id_is_rejected():
    data = sample_case()
    data["fields"]["decision"]["evidence"] = ["ev_missing"]
    with pytest.raises(ValidationError):
        parse_record(data)


def test_record_needs_evidence():
    data = sample_case()
    data["evidence"] = []
    with pytest.raises(ValidationError):
        parse_record(data)


def test_make_id_is_stable():
    assert make_id("rec", "a", 1) == make_id("rec", "a", 1)
    assert make_id("rec", "a", 1) != make_id("rec", "a", 2)


def test_load_settings_reads_config():
    settings = load_settings()
    assert settings.sectioning.max_tokens > settings.sectioning.target_tokens
    assert settings.llm.provider in ("ollama", "anthropic")
    assert settings.path("inbox").name == "inbox"
