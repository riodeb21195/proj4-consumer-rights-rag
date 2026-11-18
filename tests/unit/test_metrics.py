import json

from rag.api.metrics import EvalCollector, load_results


def _write(path, name, variant, created, hr):
    (path / name).write_text(
        json.dumps(
            {
                "variant": variant,
                "created_at": created,
                "metrics": {"hit_rate@5": hr, "mrr": hr / 2},
            }
        )
    )


def test_collector_exposes_latest_and_previous(tmp_path):
    _write(tmp_path, "a.json", "hybrid", "2026-01-01", 0.8)
    _write(tmp_path, "b.json", "hybrid", "2026-01-02", 0.7)
    _write(tmp_path, "c.json", "vector", "2026-01-01", 0.6)
    (tmp_path / "broken.json").write_text("{")
    (tmp_path / "other.json").write_text("[]")
    families = {f.name: f for f in EvalCollector(tmp_path, 0.6).collect()}
    samples = {
        (s.labels.get("variant"), s.labels.get("run")): s.value
        for s in families["rag_eval_hit_rate"].samples
    }
    assert samples[("hybrid", "latest")] == 0.7
    assert samples[("hybrid", "previous")] == 0.8
    assert samples[("vector", "latest")] == 0.6
    assert families["rag_eval_hit_rate_threshold"].samples[0].value == 0.6
    assert len(families["rag_eval_mrr"].samples) == 3


def test_load_results_sorted(tmp_path):
    _write(tmp_path, "z.json", "v", "2026-01-01", 0.1)
    _write(tmp_path, "a.json", "v", "2026-02-01", 0.2)
    assert [r["file"] for r in load_results(tmp_path)] == ["z.json", "a.json"]
