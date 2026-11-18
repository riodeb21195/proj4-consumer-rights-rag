"""Text embeddings: sentence-transformers on CPU, plus a deterministic fake for tests."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np

log = logging.getLogger(__name__)

Vector = np.ndarray[Any, np.dtype[np.float32]]


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed_passages(self, texts: Sequence[str]) -> Vector: ...

    def embed_query(self, text: str) -> Vector: ...


class SentenceTransformerEmbedder:
    """Wraps a sentence-transformers model. E5 models need "query: " / "passage: " prefixes."""

    def __init__(self, model_name: str, batch_size: int = 16, device: str = "cpu") -> None:
        from sentence_transformers import SentenceTransformer  # heavy import, only when used

        self.model_name = model_name
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name, device=device)
        dim = self._model.get_sentence_embedding_dimension()
        if dim is None:
            raise ValueError(f"{model_name} does not report an embedding dimension")
        self.dim = int(dim)
        self._e5 = "e5" in model_name.lower()
        log.info("embedding model loaded", extra={"model": model_name, "dim": self.dim})

    def _encode(self, texts: Sequence[str]) -> Vector:
        vectors = self._model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def embed_passages(self, texts: Sequence[str]) -> Vector:
        prefix = "passage: " if self._e5 else ""
        return self._encode([prefix + t for t in texts])

    def embed_query(self, text: str) -> Vector:
        prefix = "query: " if self._e5 else ""
        return np.asarray(self._encode([prefix + text])[0], dtype=np.float32)


_TOKEN = re.compile(r"\w+", re.UNICODE)


class FakeEmbedder:
    """Hashing-trick bag of words. Deterministic and fast; lexical overlap -> high similarity.

    Lets tests (and machines without PyTorch) run the full pipeline. Not for real retrieval.
    """

    def __init__(self, dim: int = 384) -> None:
        self.model_name = "fake-hashing"
        self.dim = dim

    def _vec(self, text: str) -> Vector:
        v = np.zeros(self.dim, dtype=np.float32)
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            v[int.from_bytes(digest[:4], "little") % self.dim] += 1.0
        norm = np.linalg.norm(v)
        if norm == 0:
            v[0] = 1.0
            return v
        return v / norm

    def embed_passages(self, texts: Sequence[str]) -> Vector:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text: str) -> Vector:
        return self._vec(text)


def make_embedder(model_name: str, batch_size: int = 16) -> Embedder:
    if model_name == "fake-hashing":
        return FakeEmbedder()
    return SentenceTransformerEmbedder(model_name, batch_size=batch_size)
