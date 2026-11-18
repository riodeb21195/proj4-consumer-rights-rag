# 0002 – Embedding model: intfloat/multilingual-e5-small

- Status: accepted
- Date: 2026-11-18

## Context
German text, CPU only (Intel MacBook 2019, no GPU), limited RAM, no paid APIs.

## Decision
`intfloat/multilingual-e5-small` via sentence-transformers:

- multilingual incl. German, 384 dimensions, 512-token window (verified in the container:
  `get_sentence_embedding_dimension() == 384`, `max_seq_length == 512`),
- small enough for CPU: ~0.11 s per long passage on the 2019 Intel CPU inside Docker
  (64 passages of ~600 chars in 7.2 s, measured 2026-11-18),
- uses the `query: ` / `passage: ` prefixes, handled in `SentenceTransformerEmbedder`.

`paraphrase-multilingual-MiniLM-L12-v2` was considered; its 128-token limit would truncate
most legal paragraphs.

## Consequences
- The model name is part of the index config: switching models triggers a full re-index.
- The column type is `vector(384)`; a model with another dimension needs a schema migration.
- A deterministic `FakeEmbedder` (hashing trick) is used in tests so they run without PyTorch.
