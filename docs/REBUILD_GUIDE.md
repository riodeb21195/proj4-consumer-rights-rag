# Rebuild Guide

Step-by-step instructions to rebuild this project by hand in an empty repository. The steps follow
the real Git history of this repo: every phase was built on a branch `phase/<n>-<name>` and merged
into `main` with `--no-ff`. Compare your result with the listed commit
(`git show --stat <hash>`, `git diff <hash> -- <file>`).

Rules for every step:

- Write the code yourself; the hints say *what* it must do, not *how*.
- Tests may be copied from this repo (`tests/…` at the listed commit) and must pass before you
  commit: `make lint` and `make test` green, then commit and merge.
- Verify versions and URLs against the real sources (PyPI, Docker Hub, gesetze-im-internet.de)
  instead of copying them blindly; they will have moved on.

| Step | Topic | Branch commit | Merge commit |
|---:|---|---|---|
| 0 | Scaffold | `44a3cc9` | `5832e6d` |
| 1 | Ingest: discover, download, parse, raw archive | `ce30870` | `a99b5fb` |
| 2 | Storage: schema and vector store | `c7e72d1` | `69001c4` |
| 3 | Processing and incremental ingest | `1fc7223` | `7e5d19a` |
| 4 | Retrieval and API | `82a8b3c` | `74a71b3` |
| 5 | Runtime stack (Docker, Airflow, Streamlit) | `87989e9` | `b00b7e8` |
| 6 | Evaluation | `6ca84eb` | `eab6be3` |
| 7 | Monitoring | `6cf906a` | `eaecb3b` |
| 8 | Failure scenarios and runbook | `a866223` | `71349ac` |
| 9 | CI/CD | `ec5e7fb` | `c251a4f` |
| 10 | README and this guide | `47a453c` + guide commit | see `git log` |

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker Desktop with ~5 GB RAM,
`gh` CLI for the GitHub step. Start with `git init` and commit `spec.md` (`c488c6a`).

---

## Step 0 – Scaffold

**Goal:** an empty but fully tooled Python package where lint and tests already run.

**Files, in this order:**
1. `.gitignore`
2. `pyproject.toml` (via `uv init --package`, then edited), `.python-version`, `uv.lock`
3. `.pre-commit-config.yaml`
4. `Makefile`
5. `.env.example`
6. `src/rag/__init__.py`, `src/rag/py.typed`
7. `src/rag/config.py`
8. `src/rag/logging.py`
9. `docs/decisions/0000-record-architecture-decisions.md`
10. `README.md` (one line is enough for now)
11. `tests/unit/test_config.py`, `tests/unit/test_logging.py`

**What the code must do:**
- `.gitignore` before the first `uv sync`: `.env`, `data/`, `*.zip`, Hugging Face caches,
  Python caches, `.venv`, IDE folders.
- `pyproject.toml`: the import package is called `rag` (`uv_build` needs `module-name`). Configure
  ruff (line length 100, a broad rule set incl. `ANN`, `S`, `B`), mypy `strict`, pytest with an
  `integration` marker and coverage `fail_under = 80`.
- `config.py`: a `pydantic-settings` class with prefix `RAG_` for all settings (DB URL, S3, model,
  chunking, …) and a cached `get_settings()`. Model the law selection as objects with a slug and
  optional paragraph ranges (the BGB is only partly consumer law). Validate the slug format.
- `logging.py`: a `logging.Formatter` that writes one JSON object per line, including fields
  passed via `extra=`.
- Makefile targets: `help up down ingest eval test lint format clean` (some stay empty for now).

**Tests green:** `tests/unit/test_config.py`, `tests/unit/test_logging.py`; `make lint`.

**Git:**
```bash
git checkout -b phase/0-scaffold
git add . && git commit -m "Scaffold project: uv, ruff, mypy, pytest, pre-commit, config and JSON logging"
git checkout main && git merge --no-ff phase/0-scaffold -m "Merge phase 0: project scaffold"
```
**Compare with:** `44a3cc9` (merge `5832e6d`)

**Questions:**
1. Why does the `.gitignore` have to exist *before* the first download or `uv sync`?
2. What do you gain from JSON logs compared to plain text when the pipeline runs in Airflow?

---

## Step 1 – Ingest: discover, download, parse, raw archive

**Goal:** fetch a law from gesetze-im-internet.de only when it changed, parse it into norms and
archive the raw XML in MinIO.

**Files, in this order:**
1. `src/rag/ingest/__init__.py`, `src/rag/ingest/hashing.py`
2. `src/rag/ingest/parse_xml.py`
3. `src/rag/ingest/download.py`
4. `src/rag/ingest/discover.py`
5. `src/rag/store/__init__.py`, `src/rag/store/object_store.py`
6. `scripts/build_fixtures.py` → generates `tests/fixtures/laws/{bgb,evo_2023,pangv_2022}.xml`
7. `tests/fixtures/mini_law.xml`, `tests/__init__.py`, `tests/conftest.py`
8. Tests (see below); `pyproject.toml`/`uv.lock` (lxml, httpx, boto3, testcontainers),
   `.pre-commit-config.yaml` (exclude the fixture XMLs)

**What the code must do:**
- First download one `xml.zip` by hand and read it: root `dokumente@builddate`, one `norm` per
  provision with `metadaten` (`jurabk`, `enbez`, `titel`, `standangabe`, `gliederungseinheit`)
  and `textdaten/text/Content/P`. Repealed provisions look like `(weggefallen)`.
- `hashing.py`: SHA-256 of bytes, and a content hash over normalised text fields (fixed separator,
  so `["ab","c"]` and `["a","bc"]` differ).
- `parse_xml.py`: XML bytes → `Law` with a list of `Norm`s (key such as `§ 312g`, title, Absätze
  as text, section path, deep-link URL). Skip repealed norms, filter by paragraph ranges
  (`312g` must sort between `312f` and `312h`), raise a dedicated error for broken XML. Never
  load the DTD or touch the network.
- `download.py`: an HTTP source that sends `If-None-Match`/`If-Modified-Since` and returns
  "not modified" on 304, retries on network errors/5xx, and unpacks the ZIP. A local source that
  reads XML from a folder (for tests and CI) with the same interface.
- `discover.py`: read `gii-toc.xml` and report configured slugs that no longer exist.
- `object_store.py`: put/get raw XML in a bucket; the key contains slug, builddate and hash, so
  the same file is stored once.
- `build_fixtures.py`: trims the real BGB to a few ranges so the fixtures stay small (~400 KB).

**Tests green:** `tests/unit/test_hashing.py`, `test_parse_xml.py`, `test_download.py`,
`test_discover.py`, `tests/integration/test_object_store.py` (MinIO via testcontainers; copy
`tests/integration/conftest.py` from `ce30870`).

**Git:**
```bash
git checkout -b phase/1-ingest
git commit -m "Ingest: discover, conditional download, XML parser, content hashing, raw archive in MinIO"
git checkout main && git merge --no-ff phase/1-ingest -m "Merge phase 1: ingest"
```
**Compare with:** `ce30870` (merge `a99b5fb`)

**Questions:**
1. Which three levels of change detection are possible, and which one does each component cover?
2. Why does the pre-commit `end-of-file-fixer` have to skip the fixture XMLs?

---

## Step 2 – Storage: schema and vector store

**Goal:** a Postgres + pgvector schema that records laws, versions, norms, index configs, chunks
and answers, and a typed Python access layer.

**Files, in this order:**
1. `db/init/01_schema.sql`
2. `src/rag/store/vector_store.py`
3. `tests/integration/conftest.py` (add a pgvector container), `tests/integration/test_vector_store.py`
4. `pyproject.toml`/`uv.lock` (psycopg, pgvector, numpy)

**What the code must do:**
- Tables: `ingest_runs` (status, stats, errors as JSON), `laws`, `law_versions` (one *current*
  version per law via a partial unique index), `norms` (content hash, version), `index_configs`
  (strategy + chunking version + model, exactly one active), `chunks` (`vector(384)`, a generated
  German `tsvector`, HNSW and GIN indexes), `answer_log`.
- Think about every foreign key: what must cascade, what must be protected?
- `VectorStore`: connect, apply the schema, a transaction context manager, CRUD for runs,
  versions, norms and configs, replace all chunks of one norm, vector search (cosine) and
  full-text search filtered by config, log answers, read lineage.
- Pitfall: `register_vector` fails while the extension does not exist yet.

**Tests green:** `tests/integration/test_vector_store.py` (+ all earlier tests).

**Git:**
```bash
git checkout -b phase/2-storage
git commit -m "Storage: Postgres/pgvector schema and vector store"
git checkout main && git merge --no-ff phase/2-storage -m "Merge phase 2: storage"
```
**Compare with:** `c7e72d1` (merge `69001c4`)

**Questions:**
1. Why are chunks tied to an `index_config` instead of storing just one embedding per norm?
2. What does the generated `tsvector` column save you compared to computing it in Python?

---

## Step 3 – Processing and incremental ingest

**Goal:** chunk, validate and embed norms and wire everything into an idempotent pipeline that
only processes what changed.

**Files, in this order:**
1. `src/rag/process/__init__.py`, `src/rag/process/chunk.py`
2. `src/rag/process/validate.py`
3. `src/rag/process/embed.py`
4. `src/rag/ingest/pipeline.py`
5. `src/rag/store/vector_store.py` (methods the pipeline needs)
6. `tests/xml_edit.py`, `tests/unit/test_chunk.py`, `test_validate.py`, `test_embed.py`,
   `tests/integration/test_pipeline.py`
7. ADRs `docs/decisions/0001` … `0005`
8. `pyproject.toml`/`uv.lock` (optional extra `ml` with sentence-transformers and CPU torch)

**What the code must do:**
- `chunk.py`: two strategies, `paragraph` and `absatz`, with a maximum length. Split overlong
  Absätze at list items, then sentences, then words. Prefix the *embedded* text with law, §,
  Absatz, heading and section; keep the displayed text clean. Export a `CHUNKING_VERSION`.
- `validate.py`: detect empty, too long and duplicate chunks and return counts.
- `embed.py`: a sentence-transformers embedder (e5 models need `query: ` / `passage: ` prefixes,
  normalised vectors) and a deterministic fake embedder for tests without torch.
- `pipeline.py`: per law, in one transaction: download (conditional) → archive in MinIO → parse →
  diff norms by content hash (add/change/remove) → re-chunk only changed norms for every config →
  embed in batches → record the run. Then fill any config that has missing chunks (new strategy
  or model) and activate it when complete. A failing law must not stop the others. CLI with
  `--laws --source --trigger --schema --no-activate`.
- Write the ADRs while the reasons are fresh: chunking, embedding model, Postgres/pgvector, MinIO,
  model runtime.

**Tests green:** the unit tests above and `tests/integration/test_pipeline.py` (new, unchanged,
amended, repealed, broken XML, strategy switch, HTTP 304, CLI).

**Git:**
```bash
git checkout -b phase/3-processing
git commit -m "Processing: structure-aware chunking, validation, embeddings, incremental ingest pipeline"
git checkout main && git merge --no-ff phase/3-processing -m "Merge phase 3: processing and incremental ingest"
```
**Compare with:** `1fc7223` (merge `7e5d19a`)

**Questions:**
1. A paragraph changes in one Absatz. Which rows in `norms` and `chunks` change, and why do the
   other chunks keep their ids?
2. Why is it acceptable that tests use a fake embedder, and which test still needs the real model?

---

## Step 4 – Retrieval and API

**Goal:** answer questions over HTTP with sources, metrics and lineage.

**Files, in this order:**
1. `src/rag/retrieval/__init__.py`, `src/rag/retrieval/search.py`
2. `src/rag/retrieval/rerank.py`
3. `src/rag/retrieval/generate.py`
4. `src/rag/api/__init__.py`, `src/rag/api/metrics.py`
5. `src/rag/api/app.py`
6. `src/rag/config.py` (retrieval and LLM settings)
7. Tests: `tests/unit/test_search.py`, `test_rerank.py`, `test_generate.py`, `test_metrics.py`,
   `tests/integration/test_api.py`

**What the code must do:**
- `search.py`: modes `vector`, `fulltext`, `hybrid`. Build the full-text query as an OR over the
  question terms (an AND query almost never matches a lay question). Fuse rankings with Reciprocal
  Rank Fusion; optionally rerank a candidate pool.
- `rerank.py`: a cross-encoder, imported lazily.
- `generate.py`: without an LLM, return the top paragraphs with citation ("§ 312g BGB") and a
  disclaimer. With Ollama, prompt it to answer only from the numbered sources; fall back to the
  extractive answer on any error.
- `metrics.py`: Prometheus counters/histograms for requests, latency, errors, retrieved chunks.
- `app.py`: app factory with `/health`, `/search`, `/ask`, `/lineage/{id}`, `/metrics`; a
  connection pool; a middleware for metrics. Every `/ask` is written to `answer_log`.
- Pitfall: with `from __future__ import annotations`, FastAPI dependency aliases
  (`Annotated[…, Depends(…)]`) must be defined at module level.

**Tests green:** the tests above plus everything before.

**Git:**
```bash
git checkout -b phase/4-retrieval-api
git commit -m "Retrieval and API: hybrid search with RRF, optional reranking and LLM, FastAPI with metrics"
git checkout main && git merge --no-ff phase/4-retrieval-api -m "Merge phase 4: retrieval and API"
```
**Compare with:** `82a8b3c` (merge `74a71b3`)

**Questions:**
1. Why RRF instead of adding cosine similarity and `ts_rank_cd`?
2. How do you get from an answer back to the exact XML file it came from?

---

## Step 5 – Runtime stack (Docker, Airflow, Streamlit)

**Goal:** `make up` starts everything, `make ingest` indexes the laws through Airflow, and the
Streamlit chat answers with sources.

**Files, in this order:**
1. `.dockerignore`, `Dockerfile` (API)
2. `db/init/00_airflow_db.sh`
3. `airflow/Dockerfile`, `airflow/dags/consumer_law_ingest.py`
4. `app/__init__.py`, `app/client.py`, `app/streamlit_app.py`, `app/Dockerfile`
5. `docker-compose.yml`
6. `scripts/trigger_ingest.sh`, `Makefile` (`up`, `down`, `ingest`, `logs`, `ps`)
7. `src/rag/ingest/discover.py` (CLI), `src/rag/process/embed.py` (compatibility),
   `tests/unit/test_app_client.py`, `tests/unit/test_discover.py`

**What the code must do:**
- API image: multi-stage build with uv, CPU-only torch, non-root user, model cache in a volume.
- Airflow (check the current stable version and its docs: `api-server`, `dag-processor`,
  `scheduler`, auth manager). Install the project into a separate venv in the Airflow image so
  its dependencies do not clash with Airflow's.
- DAG: daily; first a task that checks the sources, then one task per law (from an env variable)
  that calls the pipeline CLI; one failing law must not skip the others.
- Compose: health checks, memory limits that fit ~5 GB, named volumes, one Postgres for both the
  index and Airflow's metadata DB.
- Streamlit: chat page with sources and a disclaimer; a sidebar to pick the retrieval mode.
- `trigger_ingest.sh`: wait until the DAG is parsed, trigger it, poll until it finishes, print
  the `ingest_runs` rows.

**Tests green:** `make lint`, `make test`; manually: `make up && make ingest`, then a question
in http://localhost:8501.

**Git:**
```bash
git checkout -b phase/5-runtime
git commit -m "Runtime: Docker images, compose stack, Airflow DAG and Streamlit UI"
git checkout main && git merge --no-ff phase/5-runtime -m "Merge phase 5: runtime stack"
```
**Compare with:** `87989e9` (merge `b00b7e8`)

**Questions:**
1. Why do the ingest tasks run one after another and not in parallel on this hardware?
2. What happens in the DAG if the TKG download fails but the others succeed?

---

## Step 6 – Evaluation

**Goal:** measure retrieval quality with real numbers and decide the default retrieval mode
with data.

**Files, in this order:**
1. `evaluation/__init__.py`, `evaluation/questions.jsonl`
2. `evaluation/run_eval.py`
3. `tests/integration/test_evaluation.py`
4. `Makefile` (`eval`), `src/rag/config.py`, `.env.example`
5. `app/streamlit_app.py` (evaluation page), API endpoint `/evaluation`
6. `evaluation/results/*.json` (from a real run), `docs/evaluation.md`,
   `docs/decisions/0006-retrieval-strategy.md`

**What the code must do:**
- At least 30 German questions in consumer language with the expected law + paragraph(s). Check
  every expected paragraph against the official text and against the indexed ranges.
- Collapse retrieved chunks to distinct paragraphs before scoring (otherwise strategies with more
  chunks are disadvantaged). Compute Hit-Rate@1/3/5/10 and MRR per variant.
- Variants: vector / full text / hybrid × paragraph / Absatz, plus hybrid with reranking.
- Save each result as JSON with timestamp, git SHA, index config and rank per question.
- A quality-gate mode: `--only-indexed`, `--gate-variant`, `--min-hit-rate`; exit 1 below the
  threshold *and* when no question is answerable.
- Build the Absatz index next to the paragraph index with `--no-activate`.
- Write down what you found and derive the default mode from it (here: vector, ADR 0006).

**Tests green:** `tests/integration/test_evaluation.py`, `tests/unit/test_download.py`.

**Git:**
```bash
git checkout -b phase/6-evaluation
git commit -m "Evaluation: 45 German test questions, Hit-Rate@k/MRR, six retrieval variants"
git checkout main && git merge --no-ff phase/6-evaluation -m "Merge phase 6: evaluation"
```
**Compare with:** `6ca84eb` (merge `eab6be3`)

**Questions:**
1. Why can adding full-text search make hybrid search *worse* than pure vector search here?
2. Why must the gate fail when zero questions are answerable?

---

## Step 7 – Monitoring

**Goal:** Prometheus scrapes the API, Grafana shows a dashboard, and an alert fires when the
evaluation gets worse.

**Files, in this order:**
1. `monitoring/prometheus.yml`
2. `monitoring/alerts.yml`
3. `monitoring/grafana/provisioning/datasources/prometheus.yml`
4. `monitoring/grafana/provisioning/dashboards/dashboards.yml`
5. `monitoring/grafana/dashboards/rag-overview.json`
6. `docker-compose.yml` (prometheus, grafana), `.env.example`

**What the code must do:**
- The API exports the latest *and* previous evaluation result per variant as gauges (step 4/6),
  plus the threshold, so alert rules need no hard-coded numbers.
- Alerts: evaluation below threshold, regression vs. previous run, API down, error rate, latency.
  Validate them with `promtool check rules`.
- Grafana: provision data source and dashboard from files (fixed `uid`), no clicking.

**Tests green:** `make lint`, `make test`; manually: http://localhost:9090/alerts shows the rules,
http://localhost:3000 the dashboard.

**Git:**
```bash
git checkout -b phase/7-monitoring
git commit -m "Monitoring: Prometheus scraping, eval and API alerts, Grafana dashboard"
git checkout main && git merge --no-ff phase/7-monitoring -m "Merge phase 7: monitoring"
```
**Compare with:** `6cf906a` (merge `eaecb3b`)

**Questions:**
1. Why is the evaluation result exposed through the API instead of pushing it to Prometheus?
2. Why does the alert threshold (0.65 on 45 questions) differ from the CI threshold (0.70 on 27)?

---

## Step 8 – Failure scenarios and runbook

**Goal:** demonstrate the four failure cases against the running stack, and document operations.

**Files, in this order:**
1. `scripts/_scenario.py`
2. `scripts/scenario_law_changed.py`
3. `scripts/scenario_paragraph_repealed.py`
4. `scripts/scenario_broken_xml.py`
5. `scripts/scenario_duplicate_ingest.py`
6. `Makefile` (`scenarios`), `docs/runbook.md`

**What the code must do:**
- Work on a private copy of a small law under its own slug, never activate a new index, and
  clean up afterwards (mind the foreign keys: delete bottom-up).
- Each scenario manipulates the XML like an upstream change would, ingests again and checks the
  result with explicit OK/FAIL lines (exit 1 on FAIL).
- Runbook: services and URLs, daily operation, typical startup and ingest problems, re-indexing,
  alerts, lineage, reset.

**Tests green:** `make lint`, `make test`, `make scenarios` (all OK).

**Git:**
```bash
git checkout -b phase/8-scenarios
git commit -m "Failure scenarios: law changed, paragraph repealed, broken XML, duplicate ingest; runbook"
git checkout main && git merge --no-ff phase/8-scenarios -m "Merge phase 8: failure scenarios"
```
**Compare with:** `a866223` (merge `71349ac`)

**Questions:**
1. In the broken-XML scenario, why is the old version still searchable afterwards?
2. Which tables does a second identical ingest write to, and which not?

---

## Step 9 – CI/CD

**Goal:** every push runs lint, tests and the evaluation gate; green `main` publishes images to
GHCR.

**Files, in this order:**
1. `.github/workflows/ci.yml`
2. `.github/workflows/cd.yml`
3. `.github/dependabot.yml`

**What the code must do:**
- CI jobs: `lint`; `test` (with the `ml` extra so the real-model test runs, model cache via
  `actions/cache`); `eval-gate`: start pgvector and MinIO with `docker run`, ingest the fixture
  laws from disk, run the evaluation with `--only-indexed` and fail below the threshold. Derive
  the threshold from a real run of exactly this job, not from a guess.
- CD: triggered by a successful CI run on `main` (`workflow_run`), build and push the API and
  Streamlit images with `GITHUB_TOKEN` (`packages: write`).
- Dependabot for uv, GitHub Actions, Dockerfiles and compose.
- Create the repository and push only `main`:
  `gh repo create <user>/proj4-consumer-rights-rag --private --source . --remote origin`.

**Tests green:** the CI run on GitHub (all three jobs), then the CD run.

**Git:**
```bash
git checkout -b phase/9-ci-cd
git commit -m "CI/CD: lint, tests, eval quality gate; GHCR image publishing; Dependabot"
git checkout main && git merge --no-ff phase/9-ci-cd -m "Merge phase 9: CI/CD"
git push -u origin main
```
**Compare with:** `ec5e7fb` (merge `c251a4f`)

**Questions:**
1. Why does the gate run on a small fixture set instead of the full five laws?
2. Why is CD triggered by `workflow_run` instead of its own `push` trigger?

---

## Step 10 – README and rebuild guide

**Goal:** a README a recruiter understands on the first screen, and this guide.

**Files, in this order:**
1. `README.md`
2. `docs/runbook.md` (corrections)
3. `docs/REBUILD_GUIDE.md`

**What the code must do:**
- First screen: the question in one sentence, CI badge, a clear "not legal advice" note, a
  Mermaid architecture diagram, the evaluation table from real results, the quickstart.
- Then: how it works, "What happens when…", design decisions (links to the ADRs), limitations.
- Every number in the README must come from a real run (`docs/evaluation.md`, `ingest_runs`).

**Tests green:** `make lint`, `make test`, CI green after the push; the Mermaid diagram renders on
GitHub.

**Git:**
```bash
git checkout -b phase/10-docs
git commit -m "README: architecture, evaluation results, quickstart, what-happens-when, limitations"
git commit -m "Rebuild guide derived from the Git history"
git checkout main && git merge --no-ff phase/10-docs -m "Merge phase 10: documentation"
git push
```
**Compare with:** `47a453c` (README); the guide commit follows it on `main`.

**Questions:**
1. Which three facts should someone know after reading only the first screen of the README?
2. Which limitation of the project would you mention first in an interview, and why?
