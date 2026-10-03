"""Loads config.yaml + .env."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class PathsConfig(BaseModel):
    inbox: Path = Path("data/inbox")
    quarantine: Path = Path("data/quarantine")
    work: Path = Path("data/work")
    library: Path = Path("data/library")
    review: Path = Path("data/review")
    reports: Path = Path("data/reports")


class OcrConfig(BaseModel):
    enabled: bool = True
    min_chars_per_page: int = 50
    language: str = "eng"


class TablesConfig(BaseModel):
    enabled: bool = True


class SectioningConfig(BaseModel):
    target_tokens: int = 5000
    max_tokens: int = 8000
    min_tokens: int = 300             # smaller sections are merged with their neighbours
    overlap_tokens: int = 200
    max_heading_levels: int = 3


class LlmConfig(BaseModel):
    provider: str = "ollama"                  # "ollama" (free, local) or "anthropic" (paid API)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b"
    ollama_context: int = 12288               # tokens the local model can read at once
    ollama_timeout: int = 1800                # seconds per call (local models can be slow)
    extract_model: str = "claude-opus-5-5"
    extract_effort: str = "medium"
    compose_model: str = "claude-opus-5-5"
    compose_effort: str = "medium"
    classify_model: str = "claude-haiku-4-5"
    classify_with_llm: bool = False
    refusal_fallback: bool = True
    max_output_tokens: int = 16000
    max_retries: int = 3
    max_concurrent_requests: int = 4
    prices_per_million: dict[str, tuple[float, float]] = Field(default_factory=lambda: {
        "claude-opus-5-5": (4.0, 20.0),
        "claude-sonnet-5-5": (2.0, 10.0),
        "claude-haiku-4-5": (1.0, 5.0),
    })


class ValidationConfig(BaseModel):
    max_shared_word_run: int = 12
    max_ngram_overlap: float = 0.15
    max_sentence_similarity: float = 0.85   # a record sentence this similar to a source sentence
    max_regenerate_attempts: int = 1        # then HUMAN_REVIEW instead of rewording again
    allow_interpretation: bool = False      # rule: no inferred / added statements
    allow_statute_quotes: bool = True
    max_quote_words: int = 40


class BatchConfig(BaseModel):
    parallel_documents: int = 1


class Settings(BaseModel):
    root: Path = Field(default_factory=Path.cwd)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    jurisdiction: str = "mixed"
    ocr: OcrConfig = Field(default_factory=OcrConfig)
    tables: TablesConfig = Field(default_factory=TablesConfig)
    sectioning: SectioningConfig = Field(default_factory=SectioningConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    batch: BatchConfig = Field(default_factory=BatchConfig)

    @property
    def anthropic_api_key(self) -> str | None:
        return os.getenv("ANTHROPIC_API_KEY")

    def path(self, name: str) -> Path:
        """Absolute path for a configured folder, e.g. settings.path("inbox")."""
        return self.root / getattr(self.paths, name)

    def ensure_dirs(self) -> None:
        for name in PathsConfig.model_fields:
            self.path(name).mkdir(parents=True, exist_ok=True)


def find_project_root(start: Path | None = None) -> Path:
    """Walk up from `start` until a folder containing config.yaml is found."""
    current = (start or Path.cwd()).resolve()
    for folder in (current, *current.parents):
        if (folder / "config.yaml").exists():
            return folder
    raise FileNotFoundError(
        "config.yaml not found. Run lke from inside the project folder."
    )


def load_settings(config_path: Path | None = None) -> Settings:
    if config_path is None:
        root = find_project_root()
        config_path = root / "config.yaml"
    else:
        config_path = config_path.resolve()
        root = config_path.parent

    load_dotenv(root / ".env")

    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return Settings(root=root, **raw)
