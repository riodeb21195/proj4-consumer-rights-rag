"""Prometheus metrics: request count, latency, errors, plus the latest evaluation results."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from prometheus_client import Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

log = logging.getLogger(__name__)

REQUESTS = Counter("rag_requests_total", "HTTP requests", ["method", "endpoint", "status"])
LATENCY = Histogram(
    "rag_request_latency_seconds",
    "HTTP request latency",
    ["endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
ERRORS = Counter("rag_errors_total", "Requests that ended in a server error", ["endpoint"])
RETRIEVED = Histogram(
    "rag_retrieved_sources", "Number of sources returned per question", buckets=(0, 1, 3, 5, 10)
)


def load_results(results_dir: Path) -> list[dict[str, Any]]:
    """All evaluation result files, oldest first."""
    results = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("unreadable evaluation result", extra={"file": str(path)})
            continue
        if isinstance(data, dict) and "metrics" in data and "variant" in data:
            data["file"] = path.name
            results.append(data)
    return sorted(results, key=lambda r: str(r.get("created_at", "")))


class EvalCollector(Collector):
    """Exposes the latest and previous evaluation of each variant on every scrape.

    Alert rules compare them (regression) and check the CI threshold.
    """

    def __init__(self, results_dir: Path, threshold: float) -> None:
        self.results_dir = results_dir
        self.threshold = threshold

    def collect(self) -> Iterator[GaugeMetricFamily]:
        hit = GaugeMetricFamily(
            "rag_eval_hit_rate", "Hit rate@k of an evaluation run", labels=["variant", "k", "run"]
        )
        mrr = GaugeMetricFamily(
            "rag_eval_mrr", "MRR of an evaluation run", labels=["variant", "run"]
        )
        by_variant: dict[str, list[dict[str, Any]]] = {}
        for result in load_results(self.results_dir):
            by_variant.setdefault(str(result["variant"]), []).append(result)
        for variant, runs in by_variant.items():
            for run_label, result in zip(("latest", "previous"), reversed(runs[-2:]), strict=False):
                for name, value in result["metrics"].items():
                    if name.startswith("hit_rate@"):
                        hit.add_metric([variant, name.split("@")[1], run_label], float(value))
                    elif name == "mrr":
                        mrr.add_metric([variant, run_label], float(value))
        yield hit
        yield mrr
        yield GaugeMetricFamily(
            "rag_eval_hit_rate_threshold", "Quality gate threshold", value=self.threshold
        )
