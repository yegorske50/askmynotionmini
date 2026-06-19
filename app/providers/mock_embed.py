"""Mock embedder — fast, deterministic, no model download.

We use a hash of the text's tokens to fill a 384-dim unit vector. This means
exact / near-exact text matches will have high cosine similarity but unrelated
texts will be near zero, which is what tests need.
"""

from __future__ import annotations

import hashlib
import math

from app.providers.base import EmbeddingProvider


def _seeded_vec(text: str, dim: int) -> list[float]:
    # Hash to a seedable, deterministic per-text vector.
    h = hashlib.sha256(text.encode("utf-8")).digest()
    # 8 floats per round; expand to dim.
    vec: list[float] = []
    i = 0
    while len(vec) < dim:
        chunk = h[i % (len(h) - 4) : (i % (len(h) - 4)) + 8]
        val = int.from_bytes(chunk, "big") / (1 << 64)
        vec.append(val - 0.5)
        i += 8
    # Add token-level signal so shared words lift the cosine
    toks = [t for t in text.lower().split() if len(t) > 2][:50]
    for t in toks:
        th = hashlib.md5(t.encode("utf-8")).digest()
        idx = int.from_bytes(th[:4], "big") % dim
        sign = 1.0 if (th[4] & 1) else -1.0
        vec[idx] += 0.3 * sign
    # normalize
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class MockEmbedder(EmbeddingProvider):
    name = "mock"
    dim = 384

    def embed_query(self, text: str) -> list[float]:
        return _seeded_vec("q::" + text, self.dim)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [_seeded_vec("p::" + t, self.dim) for t in texts]
