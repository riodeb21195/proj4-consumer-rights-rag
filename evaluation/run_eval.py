"""Retrieval evaluation: Hit-Rate@k and MRR over evaluation/questions.jsonl.

A question counts as a hit at k if one of its expected (law, paragraph) pairs is among the first
k *distinct paragraphs* retrieved. Ranking by distinct paragraphs keeps the comparison fair
between chunking strategies that produce different numbers of chunks per paragraph.

Usage (inside the api container, see `make eval`):
    python -m evaluation.run_eval                       # all variants, results saved
    python -m evaluation.run_eval --variants vector-paragraph --only-indexed \
        --gate-variant vector-paragraph --min-hit-rate 0.70  # CI quality gate
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rag.config import get_settings
from rag.logging import configure_logging
from rag.process.chunk import CHUNKING_VERSION
from rag.process.embed import Embedder, make_embedder
from rag.retrieval.search import Mode, Reranker, Searcher
from rag.store.vector_store import VectorStore

log = logging.getLogger("evaluation")

HERE = Path(__file__).resolve().parent
KS = (1, 3, 5, 10)


@dataclass(frozen=True)
class Variant:
    name: str
    mode: Mode
    chunking_strategy: str
    rerank: bool = False


VARIANTS = {
    v.name: v
    for v in (
        Variant("vector-paragraph", "vector", "paragraph"),
        Variant("fulltext-paragraph", "fulltext", "paragraph"),
        Variant("hybrid-paragraph", "hybrid", "paragraph"),
        Variant("hybrid-absatz", "hybrid", "absatz"),
        Variant("vector-absatz", "vector", "absatz"),
        Variant("hybrid-paragraph-rerank", "hybrid", "paragraph", rerank=True),
    )
}
DEFAULT_VARIANTS = [
    "vector-paragraph",
    "fulltext-paragraph",
    "hybrid-paragraph",
    "vector-absatz",
    "hybrid-absatz",
]


def load_questions(path: Path) -> list[dict[str, Any]]:
    questions = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    for q in questions:
        if not q.get("question") or not q.get("expected"):
            raise ValueError(f"invalid question: {q}")
    return questions


def ranked_paragraphs(hits: list[Any]) -> list[tuple[str, str]]:
    """Distinct (law_slug, paragraph) in retrieval order."""
    return list(dict.fromkeys((h.law_slug, h.paragraph) for h in hits))


def score(questions: list[dict[str, Any]], rankings: list[list[tuple[str, str]]]) -> dict[str, Any]:
    per_question = []
    hits_at = {k: 0 for k in KS}
    rr_sum = 0.0
    for q, ranking in zip(questions, rankings, strict=True):
        expected = {(e["law"], e["paragraph"]) for e in q["expected"]}
        rank = next((i for i, p in enumerate(ranking, start=1) if p in expected), None)
        for k in KS:
            if rank is not None and rank <= k:
                hits_at[k] += 1
        rr_sum += 1.0 / rank if rank else 0.0
        per_question.append(
            {"id": q["id"], "rank": rank, "top": [f"{law} {para}" for law, para in ranking[:5]]}
        )
    n = len(questions) or 1
    metrics: dict[str, float] = {f"hit_rate@{k}": round(hits_at[k] / n, 4) for k in KS}
    metrics["mrr"] = round(rr_sum / n, 4)
    return {"metrics": metrics, "per_question": per_question}


def indexed_paragraphs(store: VectorStore, config_id: int) -> set[tuple[str, str]]:
    rows = store.conn.execute(
        "SELECT DISTINCT law_slug, paragraph FROM chunks WHERE index_config_id = %s", (config_id,)
    ).fetchall()
    return {(r["law_slug"], r["paragraph"]) for r in rows}


def find_config(store: VectorStore, strategy: str, model: str) -> int | None:
    row = store.conn.execute(
        """SELECT id FROM index_configs WHERE chunking_strategy = %s AND chunking_version = %s
           AND embedding_model = %s""",
        (strategy, CHUNKING_VERSION, model),
    ).fetchone()
    return int(row["id"]) if row else None


def git_sha() -> str:
    if os.environ.get("GIT_SHA"):
        return os.environ["GIT_SHA"]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            cwd=HERE,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def evaluate(
    store: VectorStore,
    embedder: Embedder,
    questions: list[dict[str, Any]],
    variant: Variant,
    *,
    only_indexed: bool = False,
    reranker: Reranker | None = None,
    candidate_pool: int = 30,
) -> dict[str, Any] | None:
    config_id = find_config(store, variant.chunking_strategy, embedder.model_name)
    if config_id is None:
        log.warning("no index for variant, skipping", extra={"variant": variant.name})
        return None
    if only_indexed:
        available = indexed_paragraphs(store, config_id)
        questions = [
            q
            for q in questions
            if all((e["law"], e["paragraph"]) in available for e in q["expected"])
        ]
    searcher = Searcher(store, embedder, candidate_pool=candidate_pool, reranker=reranker)
    rankings = []
    for q in questions:
        hits = searcher.search(
            q["question"],
            mode=variant.mode,
            k=max(KS) * 3,  # several chunks can belong to one paragraph
            config_id=config_id,
            rerank=variant.rerank,
        )
        rankings.append(ranked_paragraphs(hits))
    result = score(questions, rankings)
    config = store.get_config(config_id)
    assert config is not None
    return {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "variant": variant.name,
        "mode": variant.mode,
        "rerank": variant.rerank,
        "index_config": {
            "id": config.id,
            "chunking_strategy": config.chunking_strategy,
            "chunking_version": config.chunking_version,
            "embedding_model": config.embedding_model,
        },
        "git_sha": git_sha(),
        "n_questions": len(questions),
        "only_indexed": only_indexed,
        **result,
    }


def save(result: dict[str, Any], results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = result["created_at"].replace(":", "").replace("-", "").split("+")[0]
    path = results_dir / f"{stamp}_{result['variant']}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def markdown_table(results: list[dict[str, Any]]) -> str:
    lines = [
        "| Variant | Questions | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        m = r["metrics"]
        lines.append(
            f"| {r['variant']} | {r['n_questions']} | {m['hit_rate@1']:.2f} | "
            f"{m['hit_rate@3']:.2f} | {m['hit_rate@5']:.2f} | {m['hit_rate@10']:.2f} | "
            f"{m['mrr']:.2f} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--questions", type=Path, default=HERE / "questions.jsonl")
    parser.add_argument("--results-dir", type=Path, default=HERE / "results")
    parser.add_argument("--variants", default=",".join(DEFAULT_VARIANTS))
    parser.add_argument("--only-indexed", action="store_true", help="skip unanswerable questions")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--gate-variant", help="variant checked against --min-hit-rate")
    parser.add_argument("--gate-k", type=int, default=5)
    parser.add_argument("--min-hit-rate", type=float)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    questions = load_questions(args.questions)
    store = VectorStore.connect(settings.database_url)
    embedder = make_embedder(settings.embedding_model, settings.embedding_batch_size)

    wanted = [VARIANTS[name] for name in args.variants.split(",")]
    reranker: Reranker | None = None
    if any(v.rerank for v in wanted):
        from rag.retrieval.rerank import CrossEncoderReranker

        reranker = CrossEncoderReranker(settings.rerank_model)

    results = []
    for variant in wanted:
        result = evaluate(
            store,
            embedder,
            questions,
            variant,
            only_indexed=args.only_indexed,
            reranker=reranker,
            candidate_pool=settings.candidate_pool,
        )
        if result is None:
            continue
        results.append(result)
        if not args.no_save:
            log.info("result saved", extra={"file": str(save(result, args.results_dir))})
    store.close()
    print(markdown_table(results))

    if args.min_hit_rate is not None and args.gate_variant:
        gate = next((r for r in results if r["variant"] == args.gate_variant), None)
        if gate is None:
            print(f"quality gate: variant {args.gate_variant} was not evaluated", file=sys.stderr)
            return 1
        if gate["n_questions"] == 0:
            print("quality gate FAILED: no answerable questions in the index", file=sys.stderr)
            return 1
        value = gate["metrics"][f"hit_rate@{args.gate_k}"]
        if value < args.min_hit_rate:
            print(
                f"quality gate FAILED: hit_rate@{args.gate_k} = {value:.3f} "
                f"< {args.min_hit_rate:.3f}",
                file=sys.stderr,
            )
            return 1
        print(f"quality gate passed: hit_rate@{args.gate_k} = {value:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
