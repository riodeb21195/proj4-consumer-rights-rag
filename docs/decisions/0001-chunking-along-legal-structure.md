# 0001 – Chunk along the legal structure (§ / Absatz)

- Status: accepted
- Date: 2026-11-18

## Context
Users ask about rights that live in specific provisions ("§ 355 BGB"). Answers must cite law and
paragraph. Fixed-size character windows would cut through Absätze and enumerations, mix
neighbouring paragraphs in one chunk and make citations ambiguous.

The XML from gesetze-im-internet.de already carries the structure: one `<norm>` per § with
`<P>` elements per Absatz and `DL/DT/DD` for enumerations. Measured on the configured laws
(2026-11-18): median § length 590 chars (BGB) to 2,158 chars (EnWG); the longest § has 32,331
chars (EnWG), so some splitting below § level is unavoidable.

## Decision
Two strategies, both versioned as `CHUNKING_VERSION` and stored in `index_configs`:

- **paragraph** (default): one chunk per §. If the § is longer than `chunk_max_chars` (2,000),
  consecutive Absätze are grouped up to that limit.
- **absatz**: one chunk per Absatz.

An Absatz that is still too long is split at enumeration lines, then sentence ends, and only as
a last resort at word boundaries. Each chunk is embedded with a short context header:
`<law> <§> Abs. <n> <heading>` plus the innermost section heading.

2,000 chars ≈ 500 tokens for German legal text, which fits the 512-token window of the
embedding model (ADR 0002).

## Consequences
- Every chunk maps to exactly one §, so citations are always precise.
- The two strategies are compared in the evaluation (`docs/evaluation.md`).
- Changing chunking logic requires bumping `CHUNKING_VERSION`; the next ingest creates a new
  index config and re-chunks every norm (old chunks remain until pruned).
