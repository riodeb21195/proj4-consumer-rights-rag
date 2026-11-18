import sys
import types

from rag.store.vector_store import SearchHit


def _hit(cid: int, text: str) -> SearchHit:
    return SearchHit(cid, 0.0, "bgb", "BGB", f"§ {cid}", None, "H", text, "s", "u", 1)


class FakeCrossEncoder:
    def __init__(self, name, device="cpu"):
        self.name = name

    def predict(self, pairs, show_progress_bar=False):
        return [len(text) for _, text in pairs]  # longer text = more relevant


def test_rerank_orders_by_cross_encoder_score(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=FakeCrossEncoder)
    )
    from rag.retrieval.rerank import CrossEncoderReranker

    reranker = CrossEncoderReranker("fake")
    hits = [_hit(1, "a"), _hit(2, "ccc"), _hit(3, "bb")]
    ranked = reranker.rerank("q", hits, top_k=2)
    assert [h.chunk_id for h in ranked] == [2, 3]
    assert ranked[0].score == 3.0
    assert reranker.rerank("q", [], top_k=2) == []
