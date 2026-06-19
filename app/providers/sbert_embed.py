"""Sentence-transformers embedding provider (multilingual-e5-small by default).

E5 models want asymmetric prefixes: "query: ..." for queries, "passage: ..."
for index-time text. We apply these inside this provider so callers stay clean.
"""

from __future__ import annotations

import threading

from app.providers.base import EmbeddingProvider


class SBertEmbedder(EmbeddingProvider):
    name = "sbert"

    _MODEL_KIND_QUERY = "query"
    _MODEL_KIND_PASSAGE = "passage"

    def __init__(self, model_name: str = "intfloat/multilingual-e5-small", dim: int = 384):
        self.model_name = model_name
        self.dim = dim
        self._model = None
        self._lock = threading.Lock()

    def _maybe_load(self):
        # Lazy load so the worker doesn't pay the cost on import.
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                    except Exception as e:  # pragma: no cover
                        raise RuntimeError(
                            "sentence-transformers / torch is not importable. "
                            "On the Mac profile, install with `uv pip install -e \".[dev]\"` "
                            "(this will fetch torch CPU wheels)."
                        ) from e
                    self._model = SentenceTransformer(self.model_name)
                    try:
                        self.dim = self._model.get_sentence_embedding_dimension()
                    except Exception:
                        pass
        return self._model

    def _prefix(self, kind: str, text: str) -> str:
        if "e5" in self.model_name.lower():
            return f"{kind}: {text.strip()}"
        return text

    def embed_query(self, text: str) -> list[float]:
        model = self._maybe_load()
        vec = model.encode(self._prefix(self._MODEL_KIND_QUERY, text), normalize_embeddings=True)
        return [float(x) for x in vec]

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        model = self._maybe_load()
        prefixed = [self._prefix(self._MODEL_KIND_PASSAGE, t) for t in texts]
        vecs = model.encode(prefixed, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        return [[float(x) for x in v] for v in vecs]
