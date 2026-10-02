import re
from pathlib import Path

import anthropic
import httpx2
import pytest

from lke.config import Settings
from lke.extract import LLMError
from lke.models import DocumentStatus
from lke.pipeline.batch import library_path, run_batch
from lke.pipeline.runner import FatalRunError, process_file
from lke.store import Checkpoint, Library, Stage
from lke.store.exporter import export_csv, export_jsonl
from tests.fakes import FakeLLM
from tests.pdf_factory import make_book


def facts_for(user: str) -> dict:
    """Pass-1 answer built from the request: one RULE per section, citing its first page."""
    title = re.search(r"Document section: (.*)", user).group(1)
    first_page = int(re.search(r"Pages: (\d+)", user).group(1))
    return {"skipped_reason": "", "items": [{
        "key": "rule-1", "record_type": "RULE", "name": f"Notice rule ({title})",
        "heading": "", "related": [{"name": "Industrial Disputes Act, 1947", "type": "STATUTE",
                                    "relation": "related_to"}],
        "identifiers": [{"kind": "provision", "value": "Section 25F",
                         "role": "Industrial Disputes Act, 1947", "pages": [first_page]}],
        "facts": [{"id": "f1", "fact_type": "requirement", "note": "notice needed",
                   "pages": [first_page], "support": "explicit", "proprietary": False}],
        "proprietary": False, "proprietary_reason": "", "quoted_provision": "",
    }]}


COMPOSED = {"records": [{"key": "rule-1", "comparison_items": [], "concept_illustrated": [],
                         "statements": [{"field": "requirements", "basis": "source",
                                         "facts": ["f1"],
                                         "text": "Prior written notice is a precondition."}]}]}


class Exploding(FakeLLM):
    """Fails on chosen calls, like a network outage half-way through."""

    def __init__(self, fail_on: set[int], error: Exception):
        super().__init__(facts_for, COMPOSED)
        self.fail_on, self.error = fail_on, error

    def complete_json(self, **kwargs):
        if len(self.calls) in self.fail_on:
            self.calls.append(kwargs)
            raise self.error
        return super().complete_json(**kwargs)


def setup(tmp_path: Path):
    settings = Settings(root=tmp_path)
    settings.ensure_dirs()
    settings.llm.max_concurrent_requests = 1          # deterministic call order in tests
    pdf = make_book(settings.path("inbox") / "labour.pdf")
    return settings, pdf, Library(library_path(settings))


def test_full_run_builds_linked_library(tmp_path):
    settings, pdf, lib = setup(tmp_path)
    report, sections, _ = process_file(pdf, settings, lib, FakeLLM(facts_for, COMPOSED))
    assert report.status == "done" and report.sections_failed == 0
    assert report.records_saved == len(sections)
    assert lib.count_records() == {"RULE": len(sections)}
    assert lib.count_entities()["PROVISION"] == 1
    record = next(lib.iter_records())
    relations = {r["relation"] for r in lib.relations_of(record.record_id)}
    assert {"part_of", "defines", "related_to"} <= relations
    assert lib.search("Section 25F")
    assert lib.get_document(report.doc_id).status == DocumentStatus.DONE
    paths = export_jsonl(lib, tmp_path / "export") + [export_csv(lib, tmp_path / "r.csv")]
    assert all(p.stat().st_size > 0 for p in paths)
    lib.close()


def test_rerun_makes_no_llm_calls(tmp_path):
    settings, pdf, lib = setup(tmp_path)
    process_file(pdf, settings, lib, FakeLLM(facts_for, COMPOSED))
    second = Exploding(fail_on=set(range(100)), error=AssertionError("must not be called"))
    report, _, _ = process_file(pdf, settings, lib, second)
    assert second.calls == [] and report.status == "done"
    lib.close()


def test_failed_section_is_retried_on_next_run(tmp_path):
    settings, pdf, lib = setup(tmp_path)
    flaky = Exploding(fail_on={0}, error=LLMError("connection dropped"))
    report, sections, _ = process_file(pdf, settings, lib, flaky)
    assert report.status == "partial" and report.sections_failed == 1
    assert lib.get_document(report.doc_id).status == DocumentStatus.FAILED
    assert len(Checkpoint(lib).failures()) == 1

    good = FakeLLM(facts_for, COMPOSED)
    report2, _, _ = process_file(pdf, settings, lib, good)
    assert report2.status == "done"
    assert len(good.calls) == 2                    # only the failed section: pass 1 + pass 2
    assert lib.count_records() == {"RULE": len(sections)}
    lib.close()


def test_bad_api_key_stops_the_run(tmp_path):
    settings, pdf, lib = setup(tmp_path)
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.AuthenticationError("invalid x-api-key",
                                          response=httpx2.Response(401, request=request), body=None)
    with pytest.raises(FatalRunError):
        process_file(pdf, settings, lib, Exploding(fail_on={0}, error=error))
    doc = lib.list_documents()[0]
    assert doc["status"] == "failed" and "stopped" in doc["error"]
    assert "running" not in str(Checkpoint(lib).summary())     # nothing left half-done
    lib.close()


def test_same_rule_from_two_documents_is_merged(tmp_path):
    settings, pdf, lib = setup(tmp_path)

    def same_name(user):
        data = facts_for(user)
        data["items"][0]["name"] = "Notice before retrenchment"
        return data

    process_file(pdf, settings, lib, FakeLLM(same_name, COMPOSED))
    copy = make_book(settings.path("inbox") / "labour_v2.pdf", body_repeat=5)
    process_file(copy, settings, lib, FakeLLM(same_name, COMPOSED))
    records = list(lib.iter_records())
    assert len(records) == 1                               # one rule, many sources
    assert len(records[0].doc_ids) == 2
    assert len(records[0].fields.requirements) == 1        # duplicate statement merged
    lib.close()


def test_parallel_dry_run_estimates_cost(tmp_path):
    settings, pdf, lib = setup(tmp_path)
    lib.close()
    (tmp_path / "config.yaml").write_text("batch:\n  parallel_documents: 2\n")
    second = make_book(settings.path("inbox") / "second.pdf", toc=True)
    result = run_batch(settings, [pdf, second], dry_run=True, workers=2)
    assert result.fatal is None and len(result.reports) == 2
    assert result.estimate["sections"] > 0 and result.estimate["high_usd"] > 0
    with Library(library_path(settings)) as lib:
        assert lib.count_records() == {}                   # nothing sent to an LLM
        assert all(Checkpoint(lib).is_done(r.doc_id, Stage.CLASSIFY) for r in result.reports)
