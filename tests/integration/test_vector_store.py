from datetime import datetime

import numpy as np
import pytest

from rag.store.vector_store import ChunkRecord, VectorStore

pytestmark = pytest.mark.integration


def _vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(384).astype(np.float32)
    return v / np.linalg.norm(v)


def _seed_law(store: VectorStore) -> tuple[int, int]:
    run_id = store.start_run("test", None)
    with store.transaction():
        store.upsert_law("pangv_2022", "PAngV", "Preisangabenverordnung")
        version_id = store.record_version(
            "pangv_2022",
            builddate=datetime(2026, 11, 2),
            stand="Stand 2026",
            xml_sha256="a" * 64,
            raw_object_key="pangv_2022/x.xml",
            source_url="https://example.test/pangv_2022/xml.zip",
            etag='"e1"',
            last_modified=None,
            run_id=run_id,
        )
    return run_id, version_id


def _add_norm(store: VectorStore, version_id: int, key: str, text: str, h: str) -> int:
    with store.transaction():
        return store.upsert_norm(
            "pangv_2022",
            norm_key=key,
            doknr=f"D{key}",
            title="Titel",
            section="Abschnitt 1",
            absaetze=[text],
            content_hash=h,
            law_version_id=version_id,
            source_url=f"https://example.test/{key}",
        )


def _chunk(text: str, seed: int, idx: int = 0) -> ChunkRecord:
    return ChunkRecord(
        idx, "§ 1", None, "Titel", text, f"PAngV § 1 Titel\n{text}", f"h{seed}", _vec(seed)
    )


def test_runs_roundtrip(store: VectorStore):
    run_id = store.start_run("manual", None)
    store.finish_run(run_id, "success", {"laws": 1}, [{"law": "x", "error": "y"}])
    run = store.get_run(run_id)
    assert run["status"] == "success"
    assert run["stats"] == {"laws": 1}
    assert run["errors"][0]["law"] == "x"


def test_index_config_is_idempotent_and_single_active(store: VectorStore):
    a = store.ensure_index_config("paragraph", "v1", "m", 384)
    assert store.ensure_index_config("paragraph", "v1", "m", 384).id == a.id
    b = store.ensure_index_config("absatz", "v1", "m", 384)
    assert store.active_config() is None
    store.activate_config(a.id)
    store.activate_config(b.id)
    assert store.active_config().id == b.id
    assert store.get_config(a.id).chunking_strategy == "paragraph"
    assert store.get_config(999) is None
    assert [c["chunk_count"] for c in store.list_configs()] == [0, 0]


def test_versions_keep_one_current(store: VectorStore):
    run_id, v1 = _seed_law(store)
    with store.transaction():
        v2 = store.record_version(
            "pangv_2022",
            builddate=datetime(2026, 11, 3),
            stand="neu",
            xml_sha256="b" * 64,
            raw_object_key="k2",
            source_url="u",
            etag=None,
            last_modified=None,
            run_id=run_id,
        )
    assert v2 != v1
    assert store.current_version("pangv_2022").xml_sha256 == "b" * 64
    assert [v["is_current"] for v in store.law_versions("pangv_2022")] == [False, True]
    store.update_validators(v2, '"e2"', "lm")
    assert store.current_version("pangv_2022").etag == '"e2"'
    assert store.current_version("unknown") is None


def test_norm_chunk_lifecycle_and_search(store: VectorStore):
    _, version_id = _seed_law(store)
    config = store.ensure_index_config("paragraph", "v1", "m", 384)
    _add_norm(store, version_id, "§ 1", "Preise sind anzugeben.", "h1")
    _add_norm(store, version_id, "§ 2", "Grundpreis je Kilogramm.", "h2")
    assert set(store.norm_hashes("pangv_2022")) == {"§ 1", "§ 2"}

    pending = store.norms_needing_chunks(config.id, "pangv_2022")
    assert [n.norm_key for n in pending] == ["§ 1", "§ 2"]
    for i, norm in enumerate(pending):
        with store.transaction():
            store.replace_chunks(
                config,
                norm,
                law_slug="pangv_2022",
                law_abbreviation="PAngV",
                stand="Stand 2026",
                chunks=[_chunk(norm.absaetze[0], i)],
            )
    assert store.norms_needing_chunks(config.id, "pangv_2022") == []
    assert store.chunk_stats(config.id)["chunks"] == 2

    hits = store.vector_search(config.id, _vec(1), 5)
    assert hits[0].text == "Grundpreis je Kilogramm."
    assert hits[0].score == pytest.approx(1.0, abs=1e-4)
    ft = store.fulltext_search(config.id, "grundpreis", 5)
    assert [h.text for h in ft] == ["Grundpreis je Kilogramm."]
    assert store.fulltext_search(config.id, "", 5) == []

    # changed norm -> needs new chunks; deleting a norm cascades to its chunks
    _add_norm(store, version_id, "§ 1", "Preise sind immer anzugeben.", "h1b")
    assert [n.norm_key for n in store.norms_needing_chunks(config.id, "pangv_2022")] == ["§ 1"]
    with store.transaction():
        assert store.delete_norms("pangv_2022", ["§ 2"]) == 1
        assert store.delete_norms("pangv_2022", []) == 0
    assert store.chunk_stats(config.id)["chunks"] == 1


def test_lineage(store: VectorStore):
    _, version_id = _seed_law(store)
    config = store.ensure_index_config("paragraph", "v1", "m", 384)
    _add_norm(store, version_id, "§ 1", "Preise sind anzugeben.", "h1")
    norm = store.norms_needing_chunks(config.id, "pangv_2022")[0]
    with store.transaction():
        store.replace_chunks(
            config,
            norm,
            law_slug="pangv_2022",
            law_abbreviation="PAngV",
            stand="s",
            chunks=[_chunk("Preise sind anzugeben.", 0)],
        )
    chunk_id = next(iter(store.chunk_fingerprints(config.id)))
    lineage = store.get_chunks([chunk_id])[0]
    assert lineage["raw_object_key"] == "pangv_2022/x.xml"
    assert lineage["xml_sha256"] == "a" * 64
    answer_id = store.log_answer("Frage?", "hybrid", config.id, [chunk_id], "Antwort", None)
    row = store.conn.execute("SELECT * FROM answer_log WHERE id = %s", (answer_id,)).fetchone()
    assert row["chunk_ids"] == [chunk_id]

    with store.transaction():
        store.touch_norms_version("pangv_2022", version_id)
