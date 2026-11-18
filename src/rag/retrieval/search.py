"""Vector, full-text and hybrid retrieval over the active index config.

Hybrid search fuses the vector and full-text rankings with Reciprocal Rank Fusion (RRF), which
needs no score calibration between the two (cosine similarity vs. ts_rank). See ADR 0006.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Literal, Protocol

from rag.process.embed import Embedder
from rag.store.vector_store import SearchHit, VectorStore

Mode = Literal["vector", "fulltext", "hybrid"]

_WORD = re.compile(r"[a-zäöüß0-9]+", re.IGNORECASE)


class Reranker(Protocol):
    def rerank(self, query: str, hits: Sequence[SearchHit], top_k: int) -> list[SearchHit]: ...


class NoActiveIndexError(RuntimeError):
    pass


def build_tsquery(question: str) -> str:
    """Turn a natural-language question into an OR query for ``to_tsquery('german', ...)``.

    ``websearch_to_tsquery`` would AND all words, which rarely matches a whole question.
    Stop words are removed by the german configuration itself.
    """
    words = [w.lower() for w in _WORD.findall(question) if len(w) > 1]
    return " | ".join(dict.fromkeys(words))


def reciprocal_rank_fusion(rankings: Sequence[Sequence[SearchHit]], k: int = 60) -> list[SearchHit]:
    """score(d) = sum over rankings of 1 / (k + rank). Hits keep the fused score."""
    scores: dict[int, float] = {}
    hits: dict[int, SearchHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
            hits.setdefault(hit.chunk_id, hit)
    ordered = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [replace(hits[cid], score=scores[cid]) for cid in ordered]


class Searcher:
    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        *,
        candidate_pool: int = 30,
        rrf_k: int = 60,
        reranker: Reranker | None = None,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.candidate_pool = candidate_pool
        self.rrf_k = rrf_k
        self.reranker = reranker

    def resolve_config(self, config_id: int | None) -> int:
        if config_id is not None:
            return config_id
        active = self.store.active_config()
        if active is None:
            raise NoActiveIndexError("no active index; run the ingest first")
        if active.embedding_model != self.embedder.model_name:
            raise NoActiveIndexError(
                f"active index uses {active.embedding_model}, "
                f"but the API loaded {self.embedder.model_name}"
            )
        return active.id

    def search(
        self,
        query: str,
        mode: Mode = "hybrid",
        k: int = 5,
        config_id: int | None = None,
        rerank: bool | None = None,
    ) -> list[SearchHit]:
        cfg = self.resolve_config(config_id)
        pool = max(self.candidate_pool, k)
        if mode == "vector":
            candidates = self.store.vector_search(cfg, self.embedder.embed_query(query), pool)
        elif mode == "fulltext":
            candidates = self.store.fulltext_search(cfg, build_tsquery(query), pool)
        elif mode == "hybrid":
            candidates = reciprocal_rank_fusion(
                [
                    self.store.vector_search(cfg, self.embedder.embed_query(query), pool),
                    self.store.fulltext_search(cfg, build_tsquery(query), pool),
                ],
                k=self.rrf_k,
            )
        else:
            raise ValueError(f"unknown mode {mode!r}")
        use_rerank = self.reranker is not None if rerank is None else rerank
        if use_rerank and self.reranker is not None:
            return self.reranker.rerank(query, candidates, k)
        return list(candidates[:k])
