from pathlib import Path

import pymupdf

from lke.config import Settings
from lke.ingest import make_doc_id, scan_inbox
from lke.ingest.cleaner import is_page_number
from lke.pipeline.stages import run_ingest
from lke.store import Checkpoint, Library, Stage, read_jsonl


def make_settings(tmp_path: Path) -> Settings:
    settings = Settings(root=tmp_path)
    settings.ensure_dirs()
    return settings


def make_text_pdf(path: Path, pages: int = 6) -> Path:
    doc = pymupdf.open()
    for n in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text((72, 40), "ACME LAW FIRM - CONFIDENTIAL TRAINING NOTES", fontsize=8)
        page.insert_text((72, 120), f"Chapter {n}: Retrenchment", fontsize=16,
                         fontname="helvetica-bold")
        page.insert_text((72, 140), "Under Section 25F of the Industrial Disputes Act, the employ-",
                         fontsize=11)
        page.insert_text((72, 155), "ment of a workman cannot be ended without notice.", fontsize=11)
        page.insert_text((290, 800), str(n), fontsize=9)
    doc.save(path)
    return path


def make_scanned_pdf(path: Path) -> Path:
    """A page that is only an image (no text layer), like a scan."""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 500), False)
    pix.clear_with(200)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=pix)
    doc.save(path)
    return path


def test_doc_id_depends_on_contents_not_name(tmp_path):
    a = make_text_pdf(tmp_path / "a.pdf")
    b = tmp_path / "renamed.pdf"
    b.write_bytes(a.read_bytes())
    assert make_doc_id(a) == make_doc_id(b)
    assert make_doc_id(a).startswith("doc_")


def test_scan_inbox_finds_only_pdfs(tmp_path):
    make_text_pdf(tmp_path / "one.PDF")
    (tmp_path / "sub").mkdir()
    make_text_pdf(tmp_path / "sub" / "two.pdf")
    (tmp_path / "notes.txt").write_text("x")
    assert [p.name for p in scan_inbox(tmp_path)] == ["one.PDF", "two.pdf"]


def test_page_number_detection():
    for text in ("12", "- 12 -", "Page 3 of 200", "xiv", "(7)"):
        assert is_page_number(text), text
    for text in ("Section 12", "1978 judgment", "Chapter 3"):
        assert not is_page_number(text), text


def test_ingest_text_pdf(tmp_path):
    settings = make_settings(tmp_path)
    pdf = make_text_pdf(settings.path("inbox") / "notes.pdf")
    with Library(settings.path("library") / "library.db") as lib:
        outcome = run_ingest(pdf, settings, lib)
        assert outcome.status == "done"
        assert outcome.pages == 6
        assert Checkpoint(lib).is_done(outcome.doc_id, Stage.INGEST)

        pages = read_jsonl(settings.path("work") / outcome.doc_id / "pages.jsonl")
        assert [p["page_number"] for p in pages] == [1, 2, 3, 4, 5, 6]
        text = pages[2]["text"]
        assert "Section 25F" in text                       # legal identifiers kept exactly
        assert "employment" in text                         # hyphenation fixed
        assert "CONFIDENTIAL TRAINING NOTES" not in text    # repeated header removed
        assert not text.rstrip().endswith("3")              # page number removed
        heading = pages[0]["lines"][0]
        assert heading["text"] == "Chapter 1: Retrenchment" and heading["bold"]

        # second run is skipped (resume)
        assert run_ingest(pdf, settings, lib).status == "skipped"


def test_corrupt_pdf_is_quarantined(tmp_path):
    settings = make_settings(tmp_path)
    bad = settings.path("inbox") / "broken.pdf"
    bad.write_bytes(b"this is not a pdf")
    with Library(settings.path("library") / "library.db") as lib:
        outcome = run_ingest(bad, settings, lib)
    assert outcome.status == "quarantined"
    assert not bad.exists()
    assert (settings.path("quarantine") / "broken.pdf").exists()
    assert (settings.path("quarantine") / "broken.pdf.error.txt").exists()


def test_encrypted_pdf_is_quarantined(tmp_path):
    settings = make_settings(tmp_path)
    path = settings.path("inbox") / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret")
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with Library(settings.path("library") / "library.db") as lib:
        assert run_ingest(path, settings, lib).status == "quarantined"


def test_scanned_page_without_ocr_is_reported(tmp_path):
    settings = make_settings(tmp_path)
    settings.ocr.enabled = False
    pdf = make_scanned_pdf(settings.path("inbox") / "scan.pdf")
    with Library(settings.path("library") / "library.db") as lib:
        outcome = run_ingest(pdf, settings, lib)
    assert outcome.status == "done"
    assert "not OCR'd" in outcome.message


def test_quarantine_still_works_when_file_is_locked(tmp_path, monkeypatch):
    import shutil
    from lke.pipeline import stages

    settings = make_settings(tmp_path)
    bad = settings.path("inbox") / "locked.pdf"
    bad.write_bytes(b"not a pdf")

    def locked(*args, **kwargs):
        raise PermissionError("[WinError 32] file in use")
    monkeypatch.setattr(stages.shutil, "move", locked)
    with Library(settings.path("library") / "library.db") as lib:
        outcome = run_ingest(bad, settings, lib)
    assert outcome.status == "quarantined"
    assert (settings.path("quarantine") / "locked.pdf").exists()
    assert "could not be moved" in (settings.path("quarantine") / "locked.pdf.error.txt").read_text()
    del shutil


def test_status_is_pending_after_ingest(tmp_path):
    from lke.models import DocumentStatus
    settings = make_settings(tmp_path)
    pdf = make_text_pdf(settings.path("inbox") / "notes.pdf")
    with Library(settings.path("library") / "library.db") as lib:
        outcome = run_ingest(pdf, settings, lib)
        assert lib.get_document(outcome.doc_id).status == DocumentStatus.PENDING
