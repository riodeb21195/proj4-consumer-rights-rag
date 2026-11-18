import numpy as np
import pytest

from rag.process.embed import FakeEmbedder
from rag.retrieval.search import NoActiveIndexError, Searcher, build_tsquery, reciprocal_rank_fusion
from rag.store.vector_store import IndexConfig, SearchHit


def hit(cid: int, score: float = 0.0, text: str = "t") -> SearchHit:
    return SearchHit(cid, score, "bgb", "BGB", f"§ {cid}", None, "H", text, "s", "u", 1)


class FakeStore:
    def __init__(self, vector, fulltext, active=...):
        self.vector, self.fulltext = vector, fulltext
        self.active = (
            IndexConfig(1, "paragraph", "v1", "fake-hashing", 384) if active is ... else active
        )
        self.calls = []

    def active_config(self):
        return self.active

    def vector_search(self, cfg, emb, limit):
        assert isinstance(emb, np.ndarray)
        self.calls.append(("vector", cfg, limit))
        return self.vector[:limit]

    def fulltext_search(self, cfg, tsquery, limit):
        self.calls.append(("fulltext", cfg, tsquery))
        return self.fulltext[:limit]


def test_build_tsquery():
    assert build_tsquery("Wie lange gilt das Widerrufsrecht? Widerrufsrecht!") == (
        "wie | lange | gilt | das | widerrufsrecht"
    )
    assert build_tsquery("a ?") == ""


def test_rrf_rewards_agreement():
    fused = reciprocal_rank_fusion([[hit(1), hit(2), hit(3)], [hit(3), hit(4)]], k=60)
    assert [h.chunk_id for h in fused][:1] == [3]
    assert fused[0].score == pytest.approx(1 / 63 + 1 / 61)
    assert {h.chunk_id for h in fused} == {1, 2, 3, 4}


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("vector", [1, 2]), ("fulltext", [3, 1]), ("hybrid", [1, 3])],
)
def test_modes(mode, expected):
    store = FakeStore([hit(1), hit(2)], [hit(3), hit(1)])
    searcher = Searcher(store, FakeEmbedder(), candidate_pool=10)
    assert [h.chunk_id for h in searcher.search("Widerruf", mode=mode, k=2)] == expected


def test_unknown_mode():
    with pytest.raises(ValueError):
        Searcher(FakeStore([], []), FakeEmbedder()).search("x", mode="magic")


def test_requires_active_index_with_same_model():
    with pytest.raises(NoActiveIndexError):
        Searcher(FakeStore([], [], active=None), FakeEmbedder()).search("x")
    other = IndexConfig(1, "paragraph", "v1", "other-model", 384)
    with pytest.raises(NoActiveIndexError):
        Searcher(FakeStore([], [], active=other), FakeEmbedder()).search("x")


def test_explicit_config_skips_active_lookup():
    store = FakeStore([hit(1)], [], active=None)
    Searcher(store, FakeEmbedder()).search("x", mode="vector", config_id=7)
    assert store.calls[0][1] == 7


class ReverseReranker:
    def rerank(self, query, hits, top_k):
        return list(reversed(hits))[:top_k]


def test_reranker_applied_and_can_be_disabled():
    store = FakeStore([hit(1), hit(2), hit(3)], [])
    searcher = Searcher(store, FakeEmbedder(), reranker=ReverseReranker())
    assert [h.chunk_id for h in searcher.search("x", mode="vector", k=2)] == [3, 2]
    assert [h.chunk_id for h in searcher.search("x", mode="vector", k=2, rerank=False)] == [1, 2]
