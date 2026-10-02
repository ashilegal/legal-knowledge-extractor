"""Builds small realistic PDFs for tests."""

from __future__ import annotations

from pathlib import Path

import pymupdf

BODY = (
    "The employer must give one month's notice in writing before retrenchment. "
    "Compensation equal to fifteen days' average pay for every completed year of "
    "continuous service is payable to the workman. "
)


class Writer:
    """Writes lines top to bottom, adding pages as needed."""

    def __init__(self):
        self.doc = pymupdf.open()
        self.page = None
        self.y = 0.0
        self.new_page()

    def new_page(self):
        self.page = self.doc.new_page()
        self.page.insert_text((72, 40), "TRAINING MATERIAL - LABOUR LAW", fontsize=8)
        self.page.insert_text((290, 815), str(self.doc.page_count), fontsize=8)
        self.y = 110.0

    def line(self, text: str, size: float = 11, bold: bool = False, gap: float = 6):
        if self.y > 760:
            self.new_page()
        font = "helvetica-bold" if bold else "helvetica"
        self.page.insert_text((72, self.y), text, fontsize=size, fontname=font)
        self.y += size + gap

    def paragraph(self, text: str, repeat: int = 1):
        words = (text * repeat).split()
        current = ""
        for w in words:
            if len(current) + len(w) > 85:
                self.line(current)
                current = w
            else:
                current = f"{current} {w}".strip()
        if current:
            self.line(current)
        self.y += 6

    def save(self, path: Path) -> Path:
        self.doc.save(path)
        return path


def make_book(path: Path, toc: bool = False, body_repeat: int = 4) -> Path:
    w = Writer()
    toc_entries = []
    chapters = [
        ("Chapter 1 Retrenchment", ["1.1 Meaning of Retrenchment", "1.2 Conditions Precedent"]),
        ("Chapter 2 Strikes and Lock-outs", ["2.1 Illegal Strikes", "2.2 Lock-outs"]),
    ]
    for chapter, subs in chapters:
        if w.y > 110:
            w.new_page()
        toc_entries.append([1, chapter, w.doc.page_count])
        w.line(chapter, size=18, bold=True, gap=12)
        w.paragraph("This chapter explains the statutory scheme. ", 1)
        for sub in subs:
            toc_entries.append([2, sub, w.doc.page_count])
            w.line(sub, size=13, bold=True, gap=8)
            w.paragraph(f"Under Section 25F of the Industrial Disputes Act, 1947, {BODY}",
                        body_repeat)
    if toc:
        w.doc.set_toc(toc_entries)
    return w.save(path)
