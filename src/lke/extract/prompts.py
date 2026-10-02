"""Load versioned prompt files from prompts/."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_REPO_PROMPTS = Path(__file__).resolve().parents[3] / "prompts"


@lru_cache(maxsize=None)
def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


def load_prompt(name: str, root: Path | None = None) -> str:
    """prompts/<name>.md from the project root, falling back to the repository copy."""
    for folder in ([root / "prompts"] if root else []) + [_REPO_PROMPTS]:
        path = folder / f"{name}.md"
        if path.exists():
            return _read(str(path))
    raise FileNotFoundError(f"prompt '{name}' not found in prompts/")
