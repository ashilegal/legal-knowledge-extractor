"""Document, Page, Section."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class Document(BaseModel):
    doc_id: str                       # SHA-256 of the file contents
    filename: str
    source_path: str
    page_count: int = 0
    status: DocumentStatus = DocumentStatus.PENDING


class Page(BaseModel):
    doc_id: str
    page_number: int                  # 1-based, as printed in the PDF viewer
    text: str
    char_count: int = 0
    is_ocr: bool = False
    ocr_confidence: float | None = None


class Section(BaseModel):
    section_id: str
    doc_id: str
    topic_path: list[str] = Field(default_factory=list)   # ["Employment Law", "Retrenchment"]
    title: str = ""
    page_start: int
    page_end: int
    text: str
    token_estimate: int = 0

    @property
    def topic(self) -> str | None:
        return self.topic_path[0] if self.topic_path else None

    @property
    def subtopic(self) -> str | None:
        return self.topic_path[1] if len(self.topic_path) > 1 else None
