from pathlib import Path

from lke.config import SectioningConfig, Settings
from lke.models import Page, TextLine
from lke.pipeline.stages import run_ingest, run_structure
from lke.store import Checkpoint, Library, Stage
from lke.structure.headings import detect_headings, numbering_depth, strip_numbering
from lke.structure.sectioner import make_sections
from tests.pdf_factory import make_book


def setup(tmp_path: Path, **book_kwargs):
    settings = Settings(root=tmp_path)
    settings.ensure_dirs()
    pdf = make_book(settings.path("inbox") / "labour_law.pdf", **book_kwargs)
    lib = Library(settings.path("library") / "library.db")
    outcome = run_ingest(pdf, settings, lib)
    return settings, lib, outcome.doc_id


def test_numbering_depth():
    assert numbering_depth("Chapter 2 Strikes") == 1
    assert numbering_depth("1.2 Conditions Precedent") == 2
    assert numbering_depth("3.4.1 Notice") == 3
    assert numbering_depth("Retrenchment means") is None


def test_strip_numbering():
    assert strip_numbering("3.5. Commercial General Liability") == "commercial general liability"
    assert strip_numbering("E. Commercial General Liability") == "commercial general liability"
    assert strip_numbering("(a) [3:298] Personal injury:") == "personal injury"
    assert strip_numbering("[3:300 - 3:309] Reserved.") == "reserved"
    assert strip_numbering("Chapter 2: Strikes") == "strikes"


def test_placeholder_headings_ignored():
    lines = [TextLine(text="[3:300 - 3:309] Reserved.", size=10, bold=True, y=0.3),
             TextLine(text="Coverage Under The Policy", size=10, bold=True, y=0.35)]
    lines += [TextLine(text="Body text " * 8, size=10, y=0.4 + i / 100) for i in range(30)]
    pages = [Page(doc_id="d", page_number=1, text="", lines=lines)]
    titles = [h.title for h in detect_headings(pages)]
    assert titles == ["Coverage Under The Policy"]


def test_headings_from_fonts(tmp_path):
    settings, lib, doc_id = setup(tmp_path)
    sections = run_structure(doc_id, settings, lib)
    paths = [s.topic_path for s in sections]
    assert ["Chapter 1 Retrenchment", "1.1 Meaning of Retrenchment"] in paths
    assert ["Chapter 2 Strikes and Lock-outs", "2.2 Lock-outs"] in paths
    for s in sections:
        assert s.text.startswith("[[p. ")                 # page markers for traceability
        assert s.page_start <= s.page_end
        assert "TRAINING MATERIAL" not in s.text            # header removed
    assert Checkpoint(lib).is_done(doc_id, Stage.SECTION)
    lib.close()


def test_headings_from_bookmarks(tmp_path):
    settings, lib, doc_id = setup(tmp_path, toc=True)
    run_structure(doc_id, settings, lib)
    import json
    structure = json.loads((settings.path("work") / doc_id / "structure.json").read_text())
    assert structure["heading_source"] == "toc"
    chapters = [c["title"] for c in structure["tree"]["children"]]
    assert chapters == ["Chapter 1 Retrenchment", "Chapter 2 Strikes and Lock-outs"]
    lib.close()


def test_large_section_is_split_with_page_tracking(tmp_path):
    settings, lib, doc_id = setup(tmp_path, body_repeat=40)
    settings.sectioning = SectioningConfig(target_tokens=600, max_tokens=900, min_tokens=50,
                                           overlap_tokens=40)
    sections = run_structure(doc_id, settings, lib)
    parts = [s for s in sections if "(part " in s.title]
    assert len(parts) >= 2
    assert all(s.token_estimate <= 1200 for s in sections)
    pages_covered = {p for s in sections for p in range(s.page_start, s.page_end + 1)}
    assert len(pages_covered) >= 3
    lib.close()


def test_no_headings_uses_document_title():
    lines = [TextLine(text=f"Plain sentence number {i} about notice pay.", size=11, y=0.2)
             for i in range(5)]
    pages = [Page(doc_id="d", page_number=1, text="", lines=lines)]
    assert detect_headings(pages) == []
    sections = make_sections("d", pages, [], "Workers Compensation Insurance",
                             SectioningConfig())
    assert len(sections) == 1
    assert sections[0].topic_path == ["Workers Compensation Insurance"]


def test_tables_kept_as_rows():
    lines = [TextLine(text="Comparison of policies", size=11, y=0.2)]
    table = [["Feature", "EBL", "CGL"], ["Administrative errors", "Covered", "Excluded"]]
    pages = [Page(doc_id="d", page_number=4, text="", lines=lines, tables=[table])]
    section = make_sections("d", pages, [], "Insurance", SectioningConfig())[0]
    assert section.has_tables
    assert "| Administrative errors | Covered | Excluded |" in section.text
