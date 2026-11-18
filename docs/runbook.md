# Runbook

Betrieb des Consumer-Rights-RAG-Stacks auf dem eigenen Rechner. Alle Befehle laufen im
Wurzelverzeichnis des Repos.

## Dienste

| Dienst | URL | Zweck |
|---|---|---|
| Streamlit | http://localhost:8501 | Chat mit Quellenangaben, Evaluationsseite |
| API | http://localhost:8000/docs | `/ask`, `/search`, `/lineage/{id}`, `/evaluation`, `/health`, `/metrics` |
| Airflow | http://localhost:8080 | DAG `consumer_law_ingest` (Login `airflow` / `airflow`, sofern nicht in `.env` gesetzt) |
| MinIO-Konsole | http://localhost:9001 | Archiv der Roh-XMLs, Bucket `raw-laws` |
| Prometheus | http://localhost:9090 | Metriken und Alarmregeln |
| Grafana | http://localhost:3000 | Dashboard „Consumer Rights RAG“ (Login `admin` / `admin`, sofern nicht gesetzt) |
| Postgres | localhost:5432 | DB `rag` (Index) und `airflow` (Metadaten von Airflow) |

## Täglicher Betrieb

- Der DAG läuft täglich (`@daily`). Ein unverändertes Gesetz kostet jeweils ein HTTP 304.
- Manueller Lauf: `make ingest` (löst den DAG aus und wartet), oder für ein einzelnes Gesetz ohne
  Airflow: `docker compose run --rm api python -m rag.ingest.pipeline --laws pangv_2022`.
- Jeder Lauf schreibt pro Gesetz eine Zeile in `ingest_runs` (Status, Statistik pro Gesetz, Fehler):

  ```sql
  SELECT id, started_at, status, trigger, stats->'index', errors
  FROM ingest_runs ORDER BY id DESC LIMIT 10;
  ```

- Welche Version eines Gesetzes indexiert ist:

  ```sql
  SELECT law_slug, builddate, stand, xml_sha256, raw_object_key, fetched_at
  FROM law_versions WHERE is_current;
  ```

## Probleme beim Start

| Symptom | Ursache / Lösung |
|---|---|
| `make up` bricht mit „unhealthy“ bei Airflow ab | Der Healthcheck über die Airflow-CLI ist auf alten CPUs langsam. `docker compose logs airflow-scheduler` prüfen; `make up` erneut ausführen. |
| Container werden wegen Speichermangel beendet (`docker compose ps` zeigt Exit 137) | Docker Desktop braucht ca. 5 GB RAM. Andere Programme schließen oder das Limit unter Docker Desktop → Resources erhöhen. |
| API `/ask` liefert 503 „no active index“ | Noch kein erfolgreicher Ingest, oder die API nutzt ein anderes Embedding-Modell als der Index. `make ingest` ausführen. |
| Erstes `/ask` dauert mehrere Sekunden | Das Modell wärmt bei der ersten Anfrage auf; danach geht es schneller. |
| Port schon belegt | `POSTGRES_PORT` in `.env` setzen oder den anderen Dienst stoppen. |

## Probleme beim Ingest

| Symptom | Was tun |
|---|---|
| Task `ingest_<gesetz>` mit `XmlParseError` fehlgeschlagen | Das heruntergeladene XML ist kaputt. Die vorherige Version bleibt indexiert (die Transaktion des Gesetzes wurde zurückgerollt). Der nächste tägliche Lauf versucht es erneut. Details: `ingest_runs.errors`. |
| Task `check_sources` fehlgeschlagen | Ein konfiguriertes Kürzel steht nicht mehr in `gii-toc.xml` (Gesetze werden umbenannt, z. B. `evo` -> `evo_2023`). `RAG_LAWS` / `DEFAULT_LAWS` und `RAG_LAW_SLUGS` anpassen. |
| `DownloadError ... HTTP 5xx` | gesetze-im-internet.de nicht erreichbar; 3 Versuche pro Lauf und 1 Wiederholung durch Airflow. |
| Validierungszähler (`empty`, `too_long`, `duplicate`) in `stats` | Nur zur Info. `empty`/`duplicate`-Chunks wurden verworfen, `too_long`-Chunks wurden indexiert (das Modell schneidet sie ab). |

## Neuindizierung

Eine Änderung an `RAG_CHUNKING_STRATEGY`, `CHUNKING_VERSION` oder `RAG_EMBEDDING_MODEL` legt eine
neue Zeile in `index_configs` an. Der nächste Ingest chunkt jede Norm für diese Konfiguration neu
und aktiviert sie nach Erfolg; die API nutzt die aktive Konfiguration. Alte Konfigurationen bleiben,
bis man sie löscht:

```sql
SELECT * FROM index_configs;                   -- chunk counts: see /health or list_configs()
DELETE FROM index_configs WHERE id = <old id>; -- cascades to its chunks
```

Einen zweiten Index zum Vergleich bauen, ohne die API umzuschalten:

```bash
docker compose run --rm -e RAG_CHUNKING_STRATEGY=absatz api \
  python -m rag.ingest.pipeline --no-activate
```

## Evaluation und Alarme

- `make eval` bewertet alle Varianten und schreibt `evaluation/results/<zeitstempel>_<variante>.json`.
  Die API exportiert das letzte und vorletzte Ergebnis pro Variante als Prometheus-Gauges.
- Alarme (Prometheus → Alerts): `RagEvalBelowThreshold` (hit_rate@5 der Standardvariante unter
  `RAG_EVAL_HIT_RATE_THRESHOLD`, 0,65 auf dem vollen Fragenset), `RagEvalRegression` (Rückgang um
  mehr als 2 Punkte gegenüber dem vorigen Lauf), `RagApiDown`, `RagApiHighErrorRate`,
  `RagAskLatencyHigh`.
- Nach einer Regression: die beiden Ergebnisdateien vergleichen (`per_question` zeigt den Rang pro
  Frage), `ingest_runs` auf geänderte Gesetze prüfen und `git log` auf Änderungen am Retrieval.

## Fehlerszenarien vorführen

```bash
make scenarios   # law changed, paragraph repealed, broken XML, duplicate ingest
```

Sie arbeiten mit einer eigenen Kopie der PAngV (`demo_pangv`) und entfernen sie danach wieder.

## Lineage einer Antwort

Jede Antwort von `/ask` enthält eine `answer_id`. `GET /lineage/{answer_id}` liefert die Frage, die
Chunk-IDs, die Gesetzesversion (builddate, „Stand“, XML-SHA-256) und den MinIO-Schlüssel des
Roh-XMLs, aus dem jeder Chunk stammt.

## Entwicklung

```bash
uv sync                 # Python 3.12; the ml extra (torch) installs only on Linux
make lint               # ruff, ruff format --check, mypy (strict)
make test               # pytest with unit + integration tests (Docker needed), coverage
make eval               # evaluation inside the api container
make scenarios          # failure-scenario demos
make help               # all targets
```

Aufbau: `src/rag/` (ingest, process, store, retrieval, api), `airflow/dags/`, `db/init/`
(Schema), `evaluation/`, `app/` (Streamlit), `monitoring/`, `scripts/`, `tests/`.

## Zurücksetzen

```bash
make down                 # stop, keep data
docker compose down -v    # stop and delete all data (index, Airflow DB, MinIO, model cache)
```
