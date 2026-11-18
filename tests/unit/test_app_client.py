import httpx
import pytest

from app.client import ApiClient, ApiError, evaluation_table


def _client(handler) -> ApiClient:
    return ApiClient(
        "http://api:8000/", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_ask_posts_question():
    def handler(request):
        assert request.url.path == "/ask"
        assert b'"mode":"vector"' in request.content.replace(b" ", b"")
        return httpx.Response(200, json={"answer": "a", "sources": []})

    assert _client(handler).ask("Frage?", mode="vector")["answer"] == "a"


def test_errors_are_wrapped():
    with pytest.raises(ApiError, match="503"):
        _client(lambda r: httpx.Response(503, json={"detail": "no index"})).health()

    def down(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ApiError, match="not reachable"):
        _client(down).evaluation()


def test_evaluation_table_keeps_latest_per_variant():
    rows = evaluation_table(
        [
            {"variant": "hybrid", "created_at": "1", "metrics": {"mrr": 0.5}},
            {"variant": "hybrid", "created_at": "2", "metrics": {"mrr": 0.6}, "n_questions": 30},
            {"variant": "vector", "created_at": "1", "metrics": {"mrr": 0.4}},
        ]
    )
    assert [(r["variant"], r["mrr"]) for r in rows] == [("hybrid", 0.6), ("vector", 0.4)]
    assert rows[0]["questions"] == 30
