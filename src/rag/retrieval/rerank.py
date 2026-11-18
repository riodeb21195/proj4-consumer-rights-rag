"""Optional cross-encoder reranking of retrieval candidates (off by default, see ADR 0006)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from rag.store.vector_store import SearchHit


class CrossEncoderReranker:
    def __init__(self, model_name: str, device: str = "cpu") -> None:
        from sentence_transformers import CrossEncoder  # heavy import, only when enabled

        self.model_name = model_name
        self._model = CrossEncoder(model_name, device=device)

    def rerank(self, query: str, hits: Sequence[SearchHit], top_k: int) -> list[SearchHit]:
        if not hits:
            return []
        scores = self._model.predict([(query, h.text) for h in hits], show_progress_bar=False)
        ranked = sorted(zip(hits, scores, strict=True), key=lambda pair: -float(pair[1]))
        return [replace(hit, score=float(score)) for hit, score in ranked[:top_k]]
