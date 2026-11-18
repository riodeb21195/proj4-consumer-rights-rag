# 0003 – Postgres + pgvector as the only index

- Status: accepted
- Date: 2026-11-18

## Context
We need vector search, German full-text search, metadata, versioning and lineage. The corpus is
small (a few thousand chunks).

## Decision
One Postgres 17 database with the pgvector extension (image `pgvector/pgvector:0.8.7-pg17`):

- `chunks.embedding vector(384)` with an HNSW index (cosine),
- `chunks.tsv` as a generated `tsvector` with the `german` configuration and a GIN index,
- relational tables for runs, law versions, norms, index configs and the answer log.

A dedicated vector database (Qdrant, Weaviate, ...) was not chosen: it would duplicate metadata,
need a second consistency mechanism and another container on a machine with little RAM.

## Consequences
- Hybrid search is plain SQL; per-law ingest is a single ACID transaction (index and metadata
  can never disagree).
- Lineage is a join: answer_log -> chunks -> norms -> law_versions -> raw XML in MinIO.
- HNSW with a `WHERE index_config_id = ...` filter uses pgvector's iterative scans (>= 0.8) to
  keep recall when several index configs coexist.
