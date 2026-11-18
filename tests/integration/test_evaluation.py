import json
import shutil

import pytest

from evaluation.run_eval import (
    VARIANTS,
    evaluate,
    load_questions,
    main,
    markdown_table,
    save,
    score,
)
from rag.config import LawSelection, Settings
from rag.ingest.download import LocalLawSource
from rag.ingest.pipeline import IngestPipeline
from rag.process.embed import FakeEmbedder
from tests.conftest import LAW_FIXTURES

pytestmark = pytest.mark.integration

QUESTIONS = [
    {
        "id": "a",
        "question": "Grundpreis pro Kilogramm angeben",
        "expected": [{"law": "pangv_2022", "paragraph": "§ 4"}],
    },
    {
        "id": "b",
        "question": "Widerrufsfrist 14 Tage",
        "expected": [{"law": "bgb", "paragraph": "§ 355"}],
    },
    {"id": "c", "question": "Mietkaution", "expected": [{"law": "bgb", "paragraph": "§ 551"}]},
]


def test_score():
    result = score(QUESTIONS[:2], [[("pangv_2022", "§ 4")], [("bgb", "§ 1"), ("bgb", "§ 355")]])
    assert result["metrics"]["hit_rate@1"] == 0.5
    assert result["metrics"]["hit_rate@3"] == 1.0
    assert result["metrics"]["mrr"] == 0.75
    assert result["per_question"][1]["rank"] == 2


@pytest.fixture
def indexed(store, raw_store, tmp_path):
    for slug in ("pangv_2022", "bgb"):
        shutil.copy(LAW_FIXTURES / f"{slug}.xml", tmp_path / f"{slug}.xml")
    for strategy in ("absatz", "paragraph"):
        settings = Settings(
            laws=[LawSelection(slug="pangv_2022"), LawSelection(slug="bgb")],
            embedding_model="fake-hashing",
            chunking_strategy=strategy,
        )
        IngestPipeline(settings, store, raw_store, LocalLawSource(tmp_path), FakeEmbedder()).run()
    return store


def test_evaluate_variants(indexed, tmp_path):
    result = evaluate(
        indexed, FakeEmbedder(), QUESTIONS, VARIANTS["hybrid-paragraph"], only_indexed=True
    )
    assert result["n_questions"] == 2  # § 551 BGB is not in the fixture set
    assert result["metrics"]["hit_rate@10"] == 1.0
    assert result["index_config"]["chunking_strategy"] == "paragraph"
    path = save(result, tmp_path / "results")
    assert json.loads(path.read_text())["variant"] == "hybrid-paragraph"
    assert "hybrid-paragraph | 2 |" in markdown_table([result])
    full = evaluate(indexed, FakeEmbedder(), QUESTIONS, VARIANTS["fulltext-paragraph"])
    assert full["n_questions"] == 3
    assert full["per_question"][2]["rank"] is None


def test_missing_index_is_skipped(store):
    assert evaluate(store, FakeEmbedder(), QUESTIONS, VARIANTS["vector-absatz"]) is None


def test_cli_quality_gate(indexed, postgres, monkeypatch, tmp_path):
    from rag.config import get_settings

    qfile = tmp_path / "q.jsonl"
    qfile.write_text("\n".join(json.dumps(q) for q in QUESTIONS))
    monkeypatch.setenv("RAG_DATABASE_URL", postgres.get_connection_url())
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "fake-hashing")
    get_settings.cache_clear()
    common = [
        "--questions",
        str(qfile),
        "--results-dir",
        str(tmp_path / "r"),
        "--variants",
        "hybrid-paragraph",
    ]
    assert (
        main(
            [
                *common,
                "--only-indexed",
                "--gate-variant",
                "hybrid-paragraph",
                "--min-hit-rate",
                "0.5",
            ]
        )
        == 0
    )
    assert (
        main([*common, "--gate-variant", "hybrid-paragraph", "--min-hit-rate", "0.99", "--no-save"])
        == 1
    )
    assert (
        main([*common, "--gate-variant", "vector-absatz", "--min-hit-rate", "0.1", "--no-save"])
        == 1
    )
    assert len(list((tmp_path / "r").glob("*.json"))) == 1
    get_settings.cache_clear()


def test_question_file_is_valid(tmp_path):
    from evaluation.run_eval import HERE

    questions = load_questions(HERE / "questions.jsonl")
    assert len(questions) >= 30
    assert len({q["id"] for q in questions}) == len(questions)
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "x", "question": "", "expected": []}')
    with pytest.raises(ValueError):
        load_questions(bad)
