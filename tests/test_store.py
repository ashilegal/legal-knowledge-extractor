from lke.models import Document, DocumentStatus, Relation, RelationType, parse_record
from lke.store import (
    Checkpoint,
    Library,
    Stage,
    StageState,
    atomic_write_json,
    atomic_write_jsonl,
    read_json,
    read_jsonl,
)
from tests.test_models import sample_case


def make_library(tmp_path) -> Library:
    return Library(tmp_path / "library.db")


def test_document_roundtrip(tmp_path):
    with make_library(tmp_path) as lib:
        lib.upsert_document(Document(doc_id="d1", filename="a.pdf", source_path="inbox/a.pdf"))
        lib.set_document_status("d1", DocumentStatus.DONE)
        assert lib.get_document("d1").status == DocumentStatus.DONE
        assert lib.get_document("missing") is None


def test_save_search_and_reload_record(tmp_path):
    with make_library(tmp_path) as lib:
        record = parse_record(sample_case())
        lib.save_record(record)
        lib.save_record(record)                      # saving twice must not duplicate
        assert lib.count_records() == {"CASE": 1}
        assert lib.get_record(record.record_id).fields.case_name == record.fields.case_name

        hits = lib.search("Section 25F")
        assert [h["record_id"] for h in hits] == [record.record_id]
        assert lib.search("retrenched notice")
        assert lib.search("insurance") == []


def test_relations(tmp_path):
    with make_library(tmp_path) as lib:
        lib.add_relation(Relation(from_id="rec_a", relation=RelationType.INTERPRETS, to_id="rec_b"))
        lib.add_relation(Relation(from_id="rec_a", relation=RelationType.INTERPRETS, to_id="rec_b"))
        assert len(lib.relations_of("rec_b")) == 1


def test_checkpoint_resume_flow(tmp_path):
    with make_library(tmp_path) as lib:
        cp = Checkpoint(lib)
        assert not cp.is_done("d1", Stage.INGEST)

        cp.start("d1", Stage.INGEST)
        cp.done("d1", Stage.INGEST, output_path=tmp_path / "pages.jsonl")
        assert cp.is_done("d1", Stage.INGEST)

        cp.start("d1", Stage.EXTRACT, "sec_1")
        cp.failed("d1", Stage.EXTRACT, "API timeout", "sec_1")
        assert cp.state("d1", Stage.EXTRACT, "sec_1") == StageState.FAILED
        assert len(cp.failures()) == 1

        cp.start("d1", Stage.EXTRACT, "sec_1")        # retry
        assert cp.attempts("d1", Stage.EXTRACT, "sec_1") == 2

    # simulate a crash: reopen the library, the 'running' unit is recovered
    with make_library(tmp_path) as lib:
        cp = Checkpoint(lib)
        assert cp.is_done("d1", Stage.INGEST)        # finished work is remembered
        assert cp.recover_interrupted() == 1
        assert cp.state("d1", Stage.EXTRACT, "sec_1") == StageState.FAILED


def test_atomic_writes(tmp_path):
    atomic_write_json(tmp_path / "x" / "data.json", {"a": "§ 25F"})
    assert read_json(tmp_path / "x" / "data.json") == {"a": "§ 25F"}

    atomic_write_jsonl(tmp_path / "rows.jsonl", [{"n": 1}, {"n": 2}])
    assert read_jsonl(tmp_path / "rows.jsonl") == [{"n": 1}, {"n": 2}]
    assert not list(tmp_path.glob("**/*.tmp"))
