# 0000 – Record architecture decisions

- Status: accepted
- Date: 2026-11-18

## Context
Several choices in this project (chunking, embedding model, vector store, retrieval strategy)
have trade-offs that are not obvious from the code alone.

## Decision
Each significant decision is recorded as a short ADR in `docs/decisions/NNNN-title.md` with the
sections *Context*, *Decision*, *Consequences* and, where useful, *Alternatives considered*.

## Consequences
Decisions are reviewable in pull requests and stay next to the code they explain.
Superseded ADRs are kept and marked as such instead of being deleted.
