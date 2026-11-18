import shutil
from pathlib import Path

import pytest

from rag.config import LawSelection, Settings
from rag.ingest.download import FetchResult, LocalLawSource
from rag.ingest.pipeline import IngestPipeline, main
from rag.process.embed import FakeEmbedder
from rag.store.object_store import RawStore
from rag.store.vector_store import VectorStore
from tests.conftest import LAW_FIXTURES
from tests.xml_edit import bump_builddate, change_text, repeal

pytestmark = pytest.mark.integration

LAWS = [
    LawSelection(slug="pangv_2022"),
    LawSelection(slug="evo_2023"),
    LawSelection(slug="bgb", ranges=[("13", "14"), ("355", "357d")]),
]


@pytest.fixture
def law_dir(tmp_path: Path) -> Path:
    for slug in ("pangv_2022", "evo_2023", "bgb"):
        shutil.copy(LAW_FIXTURES / f"{slug}.xml", tmp_path / f"{slug}.xml")
    return tmp_path


def _pipeline(store, raw_store, law_dir, **overrides) -> IngestPipeline:
    settings = Settings(laws=LAWS, embedding_model="fake-hashing", **overrides)
    return IngestPipeline(settings, store, raw_store, LocalLawSource(law_dir), FakeEmbedder())


def _by_slug(summary):
    return {r.slug: r for r in summary.laws}


def test_first_ingest_indexes_everything(store: VectorStore, raw_store: RawStore, law_dir):
    summary = _pipeline(store, raw_store, law_dir).run()
    results = _by_slug(summary)
    assert summary.status == "success"
    assert {r.status for r in summary.laws} == {"new"}
    assert results["bgb"].norms_added == 2 + 13  # §§ 13-14 and §§ 355, 356, 356a-f, 357, 357a-d
    assert store.active_config().id == summary.index_config_id
    stats = store.chunk_stats(summary.index_config_id)
    assert stats["laws"] == 3
    assert stats["chunks"] == sum(r.chunks_written for r in summary.laws)
    version = store.current_version("pangv_2022")
    assert raw_store.exists(store.law_versions("pangv_2022")[0]["raw_object_key"])
    assert version.stand.startswith("Zuletzt geändert")
    run = store.get_run(summary.run_id)
    assert run["status"] == "success"
    assert run["stats"]["laws"]["evo_2023"]["status"] == "new"


def test_double_ingest_creates_no_duplicates(store, raw_store, law_dir):
    pipeline = _pipeline(store, raw_store, law_dir)
    first = pipeline.run()
    before = store.chunk_fingerprints(first.index_config_id)
    second = pipeline.run()
    assert {r.status for r in second.laws} == {"unchanged"}
    assert sum(r.chunks_written for r in second.laws) == 0
    assert store.chunk_fingerprints(second.index_config_id) == before
    assert len(store.law_versions("bgb")) == 1


def test_changed_paragraph_only_touches_its_chunks(store, raw_store, law_dir):
    pipeline = _pipeline(store, raw_store, law_dir)
    first = pipeline.run()
    before = store.chunk_fingerprints(first.index_config_id)
    change_text(law_dir / "bgb.xml", "§ 355", "beträgt 14 Tage", "beträgt 30 Tage")
    bump_builddate(law_dir / "bgb.xml")

    second = pipeline.run()
    bgb = _by_slug(second)["bgb"]
    assert bgb.status == "updated"
    assert (bgb.norms_changed, bgb.norms_added, bgb.norms_removed) == (1, 0, 0)
    assert _by_slug(second)["pangv_2022"].status == "unchanged"

    after = store.chunk_fingerprints(second.index_config_id)
    replaced = set(before) - set(after)
    assert replaced and len(after) == len(before)
    rows = store.get_chunks(sorted(set(after) - set(before)))
    assert {r["paragraph"] for r in rows} == {"§ 355"}
    assert "30 Tage" in rows[0]["text"]
    # every other chunk is byte-for-byte the same row
    for chunk_id in set(before) & set(after):
        assert before[chunk_id] == after[chunk_id]
    versions = store.law_versions("bgb")
    assert [v["is_current"] for v in versions] == [False, True]
    bgb_rows = [r for r in store.get_chunks(list(after)) if r["law_slug"] == "bgb"]
    assert all(r["law_version_id"] == versions[-1]["id"] for r in bgb_rows)


def test_repealed_paragraph_disappears(store, raw_store, law_dir):
    pipeline = _pipeline(store, raw_store, law_dir)
    first = pipeline.run()
    repeal(law_dir / "pangv_2022.xml", "§ 4")
    second = pipeline.run()
    pangv = _by_slug(second)["pangv_2022"]
    assert pangv.norms_removed == 1
    assert "§ 4" not in store.norm_hashes("pangv_2022")
    remaining = store.get_chunks(list(store.chunk_fingerprints(first.index_config_id)))
    assert not [r for r in remaining if r["law_slug"] == "pangv_2022" and r["paragraph"] == "§ 4"]


def test_broken_xml_is_skipped_and_reported(store, raw_store, law_dir):
    (law_dir / "evo_2023.xml").write_bytes(b"<dokumente><norm>kaputt")
    summary = _pipeline(store, raw_store, law_dir).run()
    results = _by_slug(summary)
    assert summary.status == "partial"
    assert results["evo_2023"].status == "failed"
    assert "XmlParseError" in results["evo_2023"].error
    assert results["pangv_2022"].status == "new"
    assert store.get_run(summary.run_id)["errors"][0]["law"] == "evo_2023"
    assert store.current_version("evo_2023") is None


def test_all_failed_does_not_activate_config(store, raw_store, tmp_path):
    summary = _pipeline(store, raw_store, tmp_path).run()  # empty dir: every law missing
    assert summary.status == "failed"
    assert store.active_config() is None


def test_strategy_change_triggers_reindex(store, raw_store, law_dir):
    first = _pipeline(store, raw_store, law_dir).run()
    second = _pipeline(store, raw_store, law_dir, chunking_strategy="absatz").run()
    assert second.index_config_id != first.index_config_id
    assert {r.status for r in second.laws} == {"unchanged"}
    assert (
        store.chunk_stats(second.index_config_id)["norms"]
        == store.chunk_stats(first.index_config_id)["norms"]
    )
    assert (
        store.chunk_stats(second.index_config_id)["chunks"]
        > store.chunk_stats(first.index_config_id)["chunks"]
    )
    assert store.active_config().id == second.index_config_id


class NotModifiedSource(LocalLawSource):
    def fetch(self, slug, etag=None, last_modified=None):
        if etag or last_modified:
            return FetchResult(slug, "http://test", None, etag, last_modified)
        result = super().fetch(slug)
        return FetchResult(slug, "http://test", result.xml, '"v1"', "lm")


def test_http_not_modified_short_circuits(store, raw_store, law_dir):
    settings = Settings(laws=LAWS[:1], embedding_model="fake-hashing")
    pipeline = IngestPipeline(
        settings, store, raw_store, NotModifiedSource(law_dir), FakeEmbedder()
    )
    pipeline.run()
    second = pipeline.run()
    assert second.laws[0].status == "not_modified"
    assert second.laws[0].norms_unchanged > 0


def test_cli_entrypoint(postgres, minio, law_dir, monkeypatch):
    from tests.integration.conftest import SCHEMA

    cfg = minio.get_config()
    monkeypatch.setenv("RAG_DATABASE_URL", postgres.get_connection_url())
    monkeypatch.setenv("RAG_S3_ENDPOINT_URL", f"http://{cfg['endpoint']}")
    monkeypatch.setenv("RAG_S3_ACCESS_KEY", cfg["access_key"])
    monkeypatch.setenv("RAG_S3_SECRET_KEY", cfg["secret_key"])
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "fake-hashing")
    from rag.config import get_settings

    get_settings.cache_clear()
    store = VectorStore.connect(postgres.get_connection_url())
    store.conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    store.close()
    code = main(
        ["--laws", "pangv_2022,evo_2023", "--source", str(law_dir), "--schema", str(SCHEMA)]
    )
    get_settings.cache_clear()
    assert code == 0
