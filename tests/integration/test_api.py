import json
import shutil

import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from rag.api.app import Services, _configure_conn, create_app
from rag.config import LawSelection, Settings
from rag.ingest.download import LocalLawSource
from rag.ingest.pipeline import IngestPipeline
from rag.process.embed import FakeEmbedder
from rag.retrieval.generate import ExtractiveGenerator
from tests.conftest import LAW_FIXTURES

pytestmark = pytest.mark.integration


@pytest.fixture
def client(store, raw_store, postgres, tmp_path):
    for slug in ("pangv_2022", "bgb"):
        shutil.copy(LAW_FIXTURES / f"{slug}.xml", tmp_path / f"{slug}.xml")
    results = tmp_path / "results"
    results.mkdir()
    (results / "r.json").write_text(
        json.dumps({"variant": "hybrid", "created_at": "2026", "metrics": {"hit_rate@5": 0.9}})
    )
    settings = Settings(
        laws=[LawSelection(slug="pangv_2022"), LawSelection(slug="bgb")],
        embedding_model="fake-hashing",
        eval_results_dir=str(results),
    )
    IngestPipeline(settings, store, raw_store, LocalLawSource(tmp_path), FakeEmbedder()).run()

    def factory(s: Settings) -> Services:
        pool = ConnectionPool(
            postgres.get_connection_url(),
            min_size=1,
            max_size=2,
            kwargs={"autocommit": True, "row_factory": dict_row},
            configure=_configure_conn,
        )
        return Services(s, pool, FakeEmbedder(), ExtractiveGenerator())

    with TestClient(create_app(settings, services_factory=factory)) as c:
        yield c


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["active_index"]["embedding_model"] == "fake-hashing"


def test_ask_returns_sources_and_lineage(client):
    resp = client.post(
        "/ask", json={"question": "Wie lange ist die Widerrufsfrist bei Verbraucherverträgen?"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sources"], body
    assert body["sources"][0]["url"].startswith("https://www.gesetze-im-internet.de/")
    assert "Rechtsberatung" in body["answer"]
    lineage = client.get(f"/lineage/{body['answer_id']}").json()
    assert [c["id"] for c in lineage["chunks"]] == sorted(s["chunk_id"] for s in body["sources"])
    assert lineage["chunks"][0]["raw_object_key"].endswith(".xml")
    assert client.get("/lineage/999999").status_code == 404


@pytest.mark.parametrize("mode", ["vector", "fulltext", "hybrid"])
def test_search_modes(client, mode):
    body = client.post("/search", json={"query": "Grundpreis", "mode": mode, "k": 3}).json()
    assert body["mode"] == mode
    assert len(body["sources"]) <= 3


def test_validation_error(client):
    assert client.post("/search", json={"query": "x"}).status_code == 422


def test_evaluation_and_metrics(client):
    assert client.get("/evaluation").json()[0]["variant"] == "hybrid"
    client.post("/search", json={"query": "Preisangabe"})
    metrics = client.get("/metrics").text
    assert 'rag_requests_total{endpoint="/search",method="POST",status="200"}' in metrics
    assert "rag_request_latency_seconds_bucket" in metrics
    assert 'rag_eval_hit_rate{k="5",run="latest",variant="hybrid"} 0.9' in metrics


def test_no_active_index_returns_503(client, store):
    store.conn.execute("UPDATE index_configs SET is_active = false")
    assert client.post("/search", json={"query": "Preise"}).status_code == 503
    assert client.post("/ask", json={"question": "Preise"}).status_code == 503
