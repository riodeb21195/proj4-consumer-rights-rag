# 0006 – Retrieval: vector search by default, hybrid and reranking optional

- Status: accepted
- Date: 2026-11-18

## Context
The spec asks for hybrid search (vector + full text) with optional, justified reranking.
All three retrieval modes and a cross-encoder reranker are implemented
(`src/rag/retrieval/search.py`, `rerank.py`): hybrid search fuses the vector and Postgres
full-text rankings with Reciprocal Rank Fusion (k = 60), which needs no calibration between
cosine similarity and `ts_rank_cd`.

The evaluation on 45 consumer questions (`docs/evaluation.md`, 2026-11-18) measured:

| Variant | Hit@5 | MRR | Latency per question (CPU) |
|---|---:|---:|---|
| vector | 0.71 | 0.55 | < 1 s |
| full text | 0.36 | 0.22 | < 1 s |
| hybrid (RRF) | 0.62 | 0.49 | < 1 s |
| hybrid + rerank | 0.82 | 0.65 | ≈ 27 s |

Full-text search fails on lay vocabulary vs. legal terms, so fusing it in lowers quality.
Down-weighting it in RRF (0.5 / 0.3 / 0.2) and an IDF-weighted full-text score did not beat
pure vector search.

## Decision
- Default `RAG_RETRIEVAL_MODE=vector`.
- Hybrid and full text stay available per request (`mode` in `/search` and `/ask`, UI sidebar)
  and are part of every evaluation run, so a better full-text component or a different corpus
  can change the decision with data.
- Reranking stays optional (`RAG_RERANK_ENABLED`, default off): best quality, but ~27 s per
  question on a 2019 Intel CPU is not acceptable for a chat UI.

## Consequences
- The default path is the fastest and, on this question set, the most accurate one.
- With a GPU or a faster CPU, enabling reranking is the first lever (+0.11 Hit@5).
- Improving lexical retrieval (synonym dictionary for lay terms, BM25 extension such as
  ParadeDB/pg_search) would make hybrid search worth re-evaluating.
