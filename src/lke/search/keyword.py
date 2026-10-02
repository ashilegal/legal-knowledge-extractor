"""SQLite FTS5 search."""

from __future__ import annotations

from lke.store import Library


def keyword_search(lib: Library, query: str, limit: int = 20) -> list[dict]:
    return [dict(row) for row in lib.search(query, limit)]
