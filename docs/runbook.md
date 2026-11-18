# Runbook

Operating the consumer-rights RAG stack locally. All commands run from the repository root.

## Services

| Service | URL | Purpose |
|---|---|---|
| Streamlit | http://localhost:8501 | Chat with citations, evaluation page |
| API | http://localhost:8000/docs | `/ask`, `/search`, `/lineage/{id}`, `/evaluation`, `/health`, `/metrics` |
| Airflow | http://localhost:8080 | DAG `consumer_law_ingest` (login `airflow` / `airflow` unless set in `.env`) |
| MinIO console | http://localhost:9001 | Raw XML archive, bucket `raw-laws` |
| Prometheus | http://localhost:9090 | Metrics and alert rules |
| Grafana | http://localhost:3000 | Dashboard "Consumer Rights RAG" (login `admin` / `admin` unless set) |
| Postgres | localhost:5432 | DB `rag` (index) and `airflow` (Airflow metadata) |

## Daily operation

- The DAG runs daily (`@daily`). Unchanged laws cost one HTTP 304 each.
- Manual run: `make ingest` (triggers the DAG and waits), or for a single law without Airflow:
  `docker compose run --rm api python -m rag.ingest.pipeline --laws pangv_2022`.
- Each run writes one row per law into `ingest_runs` (status, per-law stats, errors):

  ```sql
  SELECT id, started_at, status, trigger, stats->'index', errors
  FROM ingest_runs ORDER BY id DESC LIMIT 10;
  ```

- Which version of a law is indexed:

  ```sql
  SELECT law_slug, builddate, stand, xml_sha256, raw_object_key, fetched_at
  FROM law_versions WHERE is_current;
  ```

## Startup problems

| Symptom | Cause / fix |
|---|---|
| `make up` aborts with "unhealthy" for Airflow | The Airflow CLI health check is slow on old CPUs. Check `docker compose logs airflow-scheduler`; re-run `make up`. |
| Containers get OOM-killed (`docker compose ps` shows exit 137) | Docker Desktop needs ~5 GB RAM. Close other apps or raise the limit in Docker Desktop → Resources. |
| API `/ask` returns 503 "no active index" | No successful ingest yet, or the API runs a different embedding model than the index. Run `make ingest`. |
| First `/ask` takes several seconds | The model warms up on the first request; subsequent requests are faster. |
| Port already in use | Set `POSTGRES_PORT` in `.env` or stop the other service. |

## Ingest problems

| Symptom | What to do |
|---|---|
| Task `ingest_<law>` failed with `XmlParseError` | The downloaded XML is broken. The previous version stays indexed (the law's transaction was rolled back). The next daily run retries. Inspect: `ingest_runs.errors`. |
| Task `check_sources` failed | A configured law slug is no longer published in `gii-toc.xml` (laws get renamed, e.g. `evo` -> `evo_2023`). Fix `RAG_LAWS` / `DEFAULT_LAWS` and `RAG_LAW_SLUGS`. |
| `DownloadError ... HTTP 5xx` | gesetze-im-internet.de unavailable; retried 3x per run and 1x by Airflow. |
| Validation counts (`empty`, `too_long`, `duplicate`) in `stats` | Informational. `empty`/`duplicate` chunks were dropped, `too_long` chunks were indexed (the model truncates them). |

## Re-indexing

Changing `RAG_CHUNKING_STRATEGY`, `CHUNKING_VERSION` or `RAG_EMBEDDING_MODEL` creates a new row in
`index_configs`. The next ingest re-chunks every norm for that config and activates it after
success; the API serves the active config. Old configs stay until removed:

```sql
SELECT * FROM index_configs;                   -- chunk counts: see /health or list_configs()
DELETE FROM index_configs WHERE id = <old id>; -- cascades to its chunks
```

Build a second index for comparison without switching the API:

```bash
docker compose run --rm -e RAG_CHUNKING_STRATEGY=absatz api \
  python -m rag.ingest.pipeline --no-activate
```

## Evaluation and alerts

- `make eval` evaluates all variants and writes `evaluation/results/<timestamp>_<variant>.json`.
  The API exports the latest and previous result per variant as Prometheus gauges.
- Alerts (Prometheus → Alerts): `RagEvalBelowThreshold` (hit_rate@5 of the default variant below
  `RAG_EVAL_HIT_RATE_THRESHOLD`, 0.65 on the full question set), `RagEvalRegression` (drop of more than 2 points vs. the previous run),
  `RagApiDown`, `RagApiHighErrorRate`, `RagAskLatencyHigh`.
- After a regression: compare the two result files (`per_question` shows the rank per question),
  check `ingest_runs` for changed laws and `git log` for retrieval changes.

## Failure-scenario demos

```bash
make scenarios   # law changed, paragraph repealed, broken XML, duplicate ingest
```

They use a private copy of the PAngV (`demo_pangv`) and remove it afterwards.

## Lineage of an answer

Every `/ask` response contains an `answer_id`. `GET /lineage/{answer_id}` returns the question,
the chunk ids, the law version (builddate, "Stand", XML SHA-256) and the MinIO key of the raw XML
each chunk came from.

## Development

```bash
uv sync                 # Python 3.12; the ml extra (torch) installs only on Linux
make lint               # ruff, ruff format --check, mypy (strict)
make test               # pytest with unit + integration tests (Docker needed), coverage
make eval               # evaluation inside the api container
make scenarios          # failure-scenario demos
make help               # all targets
```

Layout: `src/rag/` (ingest, process, store, retrieval, api), `airflow/dags/`, `db/init/`
(schema), `evaluation/`, `app/` (Streamlit), `monitoring/`, `scripts/`, `tests/`.

## Reset

```bash
make down                 # stop, keep data
docker compose down -v    # stop and delete all data (index, Airflow DB, MinIO, model cache)
```
