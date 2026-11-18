# 0005 – Model runtime only in Linux containers

- Status: accepted
- Date: 2026-11-18

## Context
PyTorch publishes no wheels for macOS x86_64 since 2.2.2. Verified on the development machine
(Intel MacBook 2019) on 2026-11-18:

- `uv add sentence-transformers` fails: torch 2.15.0 has wheels only for
  manylinux x86_64/aarch64, macOS arm64 and Windows,
- pinning torch 2.2.2 installs, but transformers 5.23 crashes on import
  (`NameError: name 'nn' is not defined`).

## Decision
- The model dependencies live in the optional extra `ml` (sentence-transformers, CPU-only torch
  from the PyTorch CPU index on Linux).
- API, ingest/Airflow and evaluation run in Linux containers that install `ml`.
- The local venv is for linting and tests; tests use `FakeEmbedder`. The one test that loads
  the real model is skipped when sentence-transformers is not installed and runs in CI.

## Consequences
- The same image runs locally, in CI and would run in production.
- Local experiments with the real model go through `docker compose run` instead of the host venv.
