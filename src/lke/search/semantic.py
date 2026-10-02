"""Embedding search over records."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from lke.store import Library
from lke.store.db import record_search_text, record_title

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
Embedder = Callable[[list[str]], Any]      # texts -> 2-D numpy array of unit vectors

INSTALL_HINT = 'Semantic search needs the optional extra: pip install -e ".[search]"'


def _numpy():
    try:
        import numpy
    except ImportError as e:
        raise RuntimeError(INSTALL_HINT) from e
    return numpy


def default_embedder(model_name: str = DEFAULT_MODEL) -> Embedder:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError(INSTALL_HINT) from e
    np = _numpy()
    model = SentenceTransformer(model_name)
    return lambda texts: np.asarray(model.encode(texts, normalize_embeddings=True))


class SemanticIndex:
    """Embeddings of every record, cached next to the library and refreshed when it changes."""

    def __init__(self, lib: Library, embed: Embedder, cache: Path):
        self.lib, self.embed, self.cache = lib, embed, cache

    def _load(self) -> tuple[list[str], list[str], Any]:
        np = _numpy()
        rows = self.lib.conn.execute(
            "SELECT record_id, updated_at FROM records ORDER BY record_id").fetchall()
        stamp = "|".join(f"{r['record_id']}@{r['updated_at']}" for r in rows)
        if self.cache.exists():
            data = np.load(self.cache, allow_pickle=False)
            if str(data["stamp"]) == stamp:
                return list(data["ids"]), list(data["titles"]), data["vectors"]
        records = list(self.lib.iter_records())
        ids = [r.record_id for r in records]
        titles = [record_title(r) for r in records]
        vectors = self.embed([record_search_text(r) for r in records]) if records \
            else np.zeros((0, 1))
        np.savez(self.cache, ids=np.array(ids), titles=np.array(titles), vectors=vectors,
                 stamp=np.array(stamp))
        return ids, titles, vectors

    def search(self, query: str, limit: int = 10) -> list[dict]:
        np = _numpy()
        ids, titles, vectors = self._load()
        if not ids:
            return []
        q = self.embed([query])[0]
        scores = vectors @ q
        best = np.argsort(-scores)[:limit]
        return [{"record_id": ids[i], "title": titles[i], "score": round(float(scores[i]), 3)}
                for i in best]
