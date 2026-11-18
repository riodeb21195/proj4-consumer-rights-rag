# Rebuild-Guide

Schritt-für-Schritt-Anleitung, um dieses Projekt in einem leeren Repository selbst nachzubauen. Die
Schritte folgen der echten Git-Historie dieses Repos: Jede Phase wurde auf einem Branch
`phase/<n>-<name>` gebaut und mit `--no-ff` in `main` gemergt. Vergleiche dein Ergebnis mit dem
angegebenen Commit (`git show --stat <hash>`, `git diff <hash> -- <datei>`).

Regeln für jeden Schritt:

- Schreib den Code selbst. Die Hinweise sagen, *was* er leisten muss, nicht *wie*.
- Tests darfst du aus diesem Repo übernehmen (`tests/…` beim angegebenen Commit). Sie müssen vor
  dem Commit grün sein: `make lint` und `make test`, dann committen und mergen.
- Prüfe Versionen und URLs an den echten Quellen (PyPI, Docker Hub, gesetze-im-internet.de),
  statt sie blind zu kopieren. Sie haben sich inzwischen wahrscheinlich geändert.

| Schritt | Thema | Branch-Commit | Merge-Commit |
|---:|---|---|---|
| 0 | Grundgerüst | `44a3cc9` | `5832e6d` |
| 1 | Ingest: Discover, Download, Parsen, Roh-Archiv | `ce30870` | `a99b5fb` |
| 2 | Storage: Schema und Vector Store | `c7e72d1` | `69001c4` |
| 3 | Processing und inkrementeller Ingest | `1fc7223` | `7e5d19a` |
| 4 | Retrieval und API | `82a8b3c` | `74a71b3` |
| 5 | Laufzeit-Stack (Docker, Airflow, Streamlit) | `87989e9` | `b00b7e8` |
| 6 | Evaluation | `6ca84eb` | `eab6be3` |
| 7 | Monitoring | `6cf906a` | `eaecb3b` |
| 8 | Fehlerszenarien und Runbook | `a866223` | `71349ac` |
| 9 | CI/CD | `ec5e7fb` | `c251a4f` |
| 10 | README und dieser Guide | `47a453c` + Guide-Commit | siehe `git log` |

Voraussetzungen: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker Desktop mit ca. 5 GB RAM,
`gh` CLI für den GitHub-Schritt. Starte mit `git init` und committe `spec.md` (`c488c6a`).

---

## Schritt 0 – Grundgerüst

**Ziel:** ein leeres, aber vollständig eingerichtetes Python-Paket, in dem Lint und Tests schon
laufen.

**Dateien, in dieser Reihenfolge:**
1. `.gitignore`
2. `pyproject.toml` (mit `uv init --package`, dann anpassen), `.python-version`, `uv.lock`
3. `.pre-commit-config.yaml`
4. `Makefile`
5. `.env.example`
6. `src/rag/__init__.py`, `src/rag/py.typed`
7. `src/rag/config.py`
8. `src/rag/logging.py`
9. `docs/decisions/0000-record-architecture-decisions.md`
10. `README.md` (eine Zeile reicht vorerst)
11. `tests/unit/test_config.py`, `tests/unit/test_logging.py`

**Was der Code leisten muss:**
- `.gitignore` vor dem ersten `uv sync`: `.env`, `data/`, `*.zip`, Hugging-Face-Caches,
  Python-Caches, `.venv`, IDE-Ordner.
- `pyproject.toml`: Das Import-Paket heißt `rag` (`uv_build` braucht dafür `module-name`).
  Konfiguriere ruff (Zeilenlänge 100, breites Regelset inkl. `ANN`, `S`, `B`), mypy `strict`,
  pytest mit einem Marker `integration` und Coverage `fail_under = 80`.
- `config.py`: eine `pydantic-settings`-Klasse mit Präfix `RAG_` für alle Einstellungen
  (DB-URL, S3, Modell, Chunking, …) und ein gecachtes `get_settings()`. Modelliere die
  Gesetzesauswahl als Objekte mit Kürzel und optionalen Paragraphenbereichen (das BGB ist nur
  teilweise Verbraucherrecht). Validiere das Format des Kürzels.
- `logging.py`: ein `logging.Formatter`, der pro Zeile ein JSON-Objekt schreibt, inklusive der
  Felder, die über `extra=` übergeben werden.
- Makefile-Targets: `help up down ingest eval test lint format clean` (einige bleiben vorerst
  leer).

**Grüne Tests:** `tests/unit/test_config.py`, `tests/unit/test_logging.py`; `make lint`.

**Git:**
```bash
git checkout -b phase/0-scaffold
git add . && git commit -m "Scaffold project: uv, ruff, mypy, pytest, pre-commit, config and JSON logging"
git checkout main && git merge --no-ff phase/0-scaffold -m "Merge phase 0: project scaffold"
```
**Vergleichen mit:** `44a3cc9` (Merge `5832e6d`)

**Verständnisfragen:**
1. Warum muss die `.gitignore` *vor* dem ersten Download oder `uv sync` existieren?
2. Was bringen JSON-Logs gegenüber Klartext, wenn die Pipeline in Airflow läuft?

---

## Schritt 1 – Ingest: Discover, Download, Parsen, Roh-Archiv

**Ziel:** ein Gesetz nur dann von gesetze-im-internet.de laden, wenn es sich geändert hat, es in
Normen zerlegen und das Roh-XML in MinIO archivieren.

**Dateien, in dieser Reihenfolge:**
1. `src/rag/ingest/__init__.py`, `src/rag/ingest/hashing.py`
2. `src/rag/ingest/parse_xml.py`
3. `src/rag/ingest/download.py`
4. `src/rag/ingest/discover.py`
5. `src/rag/store/__init__.py`, `src/rag/store/object_store.py`
6. `scripts/build_fixtures.py` → erzeugt `tests/fixtures/laws/{bgb,evo_2023,pangv_2022}.xml`
7. `tests/fixtures/mini_law.xml`, `tests/__init__.py`, `tests/conftest.py`
8. Tests (siehe unten); `pyproject.toml`/`uv.lock` (lxml, httpx, boto3, testcontainers),
   `.pre-commit-config.yaml` (Fixture-XMLs ausnehmen)

**Was der Code leisten muss:**
- Lade zuerst ein `xml.zip` von Hand herunter und lies es: Wurzel `dokumente@builddate`, eine
  `norm` pro Vorschrift mit `metadaten` (`jurabk`, `enbez`, `titel`, `standangabe`,
  `gliederungseinheit`) und `textdaten/text/Content/P`. Aufgehobene Vorschriften sehen aus wie
  `(weggefallen)`.
- `hashing.py`: SHA-256 von Bytes und ein Content-Hash über normalisierte Textfelder (mit festem
  Trennzeichen, damit `["ab","c"]` und `["a","bc"]` verschieden sind).
- `parse_xml.py`: XML-Bytes → `Law` mit einer Liste von `Norm`s (Schlüssel wie `§ 312g`, Titel,
  Absätze als Text, Gliederungspfad, Deep-Link-URL). Aufgehobene Normen überspringen, nach
  Paragraphenbereichen filtern (`312g` muss zwischen `312f` und `312h` sortiert werden), bei
  kaputtem XML einen eigenen Fehler werfen. Niemals die DTD laden oder ins Netz gehen.
- `download.py`: eine HTTP-Quelle, die `If-None-Match`/`If-Modified-Since` mitschickt, bei 304
  „nicht geändert“ zurückgibt, bei Netzwerkfehlern/5xx wiederholt und das ZIP entpackt. Dazu eine
  lokale Quelle mit derselben Schnittstelle, die XML aus einem Ordner liest (für Tests und CI).
- `discover.py`: `gii-toc.xml` lesen und konfigurierte Kürzel melden, die es nicht mehr gibt.
- `object_store.py`: Roh-XML in einen Bucket legen und lesen. Der Schlüssel enthält Kürzel,
  builddate und Hash, damit dieselbe Datei nur einmal gespeichert wird.
- `build_fixtures.py`: kürzt das echte BGB auf einige Bereiche, damit die Fixtures klein bleiben
  (ca. 400 KB).

**Grüne Tests:** `tests/unit/test_hashing.py`, `test_parse_xml.py`, `test_download.py`,
`test_discover.py`, `tests/integration/test_object_store.py` (MinIO über testcontainers;
`tests/integration/conftest.py` aus `ce30870` übernehmen).

**Git:**
```bash
git checkout -b phase/1-ingest
git commit -m "Ingest: discover, conditional download, XML parser, content hashing, raw archive in MinIO"
git checkout main && git merge --no-ff phase/1-ingest -m "Merge phase 1: ingest"
```
**Vergleichen mit:** `ce30870` (Merge `a99b5fb`)

**Verständnisfragen:**
1. Welche drei Ebenen der Change Detection gibt es, und welche Komponente deckt welche ab?
2. Warum muss der pre-commit-Hook `end-of-file-fixer` die Fixture-XMLs auslassen?

---

## Schritt 2 – Storage: Schema und Vector Store

**Ziel:** ein Schema in Postgres + pgvector, das Gesetze, Versionen, Normen, Index-Konfigurationen,
Chunks und Antworten festhält, plus eine typisierte Zugriffsschicht in Python.

**Dateien, in dieser Reihenfolge:**
1. `db/init/01_schema.sql`
2. `src/rag/store/vector_store.py`
3. `tests/integration/conftest.py` (pgvector-Container ergänzen), `tests/integration/test_vector_store.py`
4. `pyproject.toml`/`uv.lock` (psycopg, pgvector, numpy)

**Was der Code leisten muss:**
- Tabellen: `ingest_runs` (Status, Statistik, Fehler als JSON), `laws`, `law_versions` (genau eine
  *aktuelle* Version pro Gesetz über einen partiellen Unique-Index), `norms` (Content-Hash,
  Version), `index_configs` (Strategie + Chunking-Version + Modell, genau eine aktiv), `chunks`
  (`vector(384)`, ein generierter deutscher `tsvector`, HNSW- und GIN-Index), `answer_log`.
- Überleg dir bei jedem Fremdschlüssel: Was soll kaskadieren, was muss geschützt sein?
- `VectorStore`: verbinden, Schema anwenden, ein Context-Manager für Transaktionen, CRUD für Läufe,
  Versionen, Normen und Konfigurationen, alle Chunks einer Norm ersetzen, Vektorsuche (Cosinus) und
  Volltextsuche gefiltert nach Konfiguration, Antworten protokollieren, Lineage lesen.
- Stolperfalle: `register_vector` schlägt fehl, solange die Extension noch nicht existiert.

**Grüne Tests:** `tests/integration/test_vector_store.py` (+ alle vorherigen Tests).

**Git:**
```bash
git checkout -b phase/2-storage
git commit -m "Storage: Postgres/pgvector schema and vector store"
git checkout main && git merge --no-ff phase/2-storage -m "Merge phase 2: storage"
```
**Vergleichen mit:** `c7e72d1` (Merge `69001c4`)

**Verständnisfragen:**
1. Warum hängen Chunks an einer `index_config`, statt nur ein Embedding pro Norm zu speichern?
2. Was spart dir die generierte `tsvector`-Spalte im Vergleich dazu, sie in Python zu berechnen?

---

## Schritt 3 – Processing und inkrementeller Ingest

**Ziel:** Normen chunken, validieren und embedden und alles zu einer idempotenten Pipeline
verbinden, die nur verarbeitet, was sich geändert hat.

**Dateien, in dieser Reihenfolge:**
1. `src/rag/process/__init__.py`, `src/rag/process/chunk.py`
2. `src/rag/process/validate.py`
3. `src/rag/process/embed.py`
4. `src/rag/ingest/pipeline.py`
5. `src/rag/store/vector_store.py` (Methoden, die die Pipeline braucht)
6. `tests/xml_edit.py`, `tests/unit/test_chunk.py`, `test_validate.py`, `test_embed.py`,
   `tests/integration/test_pipeline.py`
7. ADRs `docs/decisions/0001` … `0005`
8. `pyproject.toml`/`uv.lock` (optionales Extra `ml` mit sentence-transformers und CPU-Torch)

**Was der Code leisten muss:**
- `chunk.py`: zwei Strategien, `paragraph` und `absatz`, mit Maximallänge. Zu lange Absätze erst
  an Aufzählungen, dann an Sätzen, dann an Wörtern teilen. Dem *eingebetteten* Text Gesetz, §,
  Absatz, Überschrift und Abschnitt voranstellen; der angezeigte Text bleibt sauber. Eine
  Konstante `CHUNKING_VERSION` exportieren.
- `validate.py`: leere, zu lange und doppelte Chunks erkennen und Zählwerte zurückgeben.
- `embed.py`: ein sentence-transformers-Embedder (e5-Modelle brauchen die Präfixe `query: ` /
  `passage: ` und normalisierte Vektoren) und ein deterministischer Fake-Embedder für Tests ohne
  Torch.
- `pipeline.py`: pro Gesetz in einer Transaktion: Download (bedingt) → in MinIO archivieren →
  parsen → Normen per Content-Hash vergleichen (neu/geändert/entfernt) → nur geänderte Normen für
  jede Konfiguration neu chunken → in Batches embedden → Lauf protokollieren. Danach jede
  Konfiguration auffüllen, der Chunks fehlen (neue Strategie oder neues Modell), und sie
  aktivieren, wenn sie vollständig ist. Ein fehlschlagendes Gesetz darf die anderen nicht
  stoppen. CLI mit `--laws --source --trigger --schema --no-activate`.
- Schreib die ADRs, solange die Gründe frisch sind: Chunking, Embedding-Modell, Postgres/pgvector,
  MinIO, Modell-Laufzeit.

**Grüne Tests:** die Unit-Tests oben und `tests/integration/test_pipeline.py` (neu, unverändert,
geändert, aufgehoben, kaputtes XML, Strategiewechsel, HTTP 304, CLI).

**Git:**
```bash
git checkout -b phase/3-processing
git commit -m "Processing: structure-aware chunking, validation, embeddings, incremental ingest pipeline"
git checkout main && git merge --no-ff phase/3-processing -m "Merge phase 3: processing and incremental ingest"
```
**Vergleichen mit:** `1fc7223` (Merge `7e5d19a`)

**Verständnisfragen:**
1. In einem Paragraphen ändert sich ein Absatz. Welche Zeilen in `norms` und `chunks` ändern sich,
   und warum behalten die anderen Chunks ihre IDs?
2. Warum ist es vertretbar, dass Tests einen Fake-Embedder nutzen, und welcher Test braucht trotzdem
   das echte Modell?

---

## Schritt 4 – Retrieval und API

**Ziel:** Fragen über HTTP mit Quellen, Metriken und Lineage beantworten.

**Dateien, in dieser Reihenfolge:**
1. `src/rag/retrieval/__init__.py`, `src/rag/retrieval/search.py`
2. `src/rag/retrieval/rerank.py`
3. `src/rag/retrieval/generate.py`
4. `src/rag/api/__init__.py`, `src/rag/api/metrics.py`
5. `src/rag/api/app.py`
6. `src/rag/config.py` (Einstellungen für Retrieval und LLM)
7. Tests: `tests/unit/test_search.py`, `test_rerank.py`, `test_generate.py`, `test_metrics.py`,
   `tests/integration/test_api.py`

**Was der Code leisten muss:**
- `search.py`: Modi `vector`, `fulltext`, `hybrid`. Die Volltext-Query als OR über die Wörter der
  Frage bauen (eine AND-Query passt fast nie auf eine Laienfrage). Rankings mit Reciprocal Rank
  Fusion zusammenführen; optional einen Kandidaten-Pool reranken.
- `rerank.py`: ein Cross-Encoder, erst bei Bedarf importiert.
- `generate.py`: ohne LLM die besten Paragraphen mit Quellenangabe („§ 312g BGB“) und Hinweis
  zurückgeben. Mit Ollama das Modell anweisen, nur aus den nummerierten Quellen zu antworten; bei
  jedem Fehler auf die extraktive Antwort zurückfallen.
- `metrics.py`: Prometheus-Counter/Histogramme für Anfragen, Latenz, Fehler und gefundene Chunks.
- `app.py`: App-Factory mit `/health`, `/search`, `/ask`, `/lineage/{id}`, `/metrics`; ein
  Connection-Pool; eine Middleware für Metriken. Jedes `/ask` wird in `answer_log` geschrieben.
- Stolperfalle: Mit `from __future__ import annotations` müssen FastAPI-Dependency-Aliase
  (`Annotated[…, Depends(…)]`) auf Modulebene definiert sein.

**Grüne Tests:** die Tests oben plus alles davor.

**Git:**
```bash
git checkout -b phase/4-retrieval-api
git commit -m "Retrieval and API: hybrid search with RRF, optional reranking and LLM, FastAPI with metrics"
git checkout main && git merge --no-ff phase/4-retrieval-api -m "Merge phase 4: retrieval and API"
```
**Vergleichen mit:** `82a8b3c` (Merge `74a71b3`)

**Verständnisfragen:**
1. Warum RRF, statt Cosinus-Ähnlichkeit und `ts_rank_cd` zu addieren?
2. Wie kommst du von einer Antwort zurück zur genauen XML-Datei, aus der sie stammt?

---

## Schritt 5 – Laufzeit-Stack (Docker, Airflow, Streamlit)

**Ziel:** `make up` startet alles, `make ingest` indexiert die Gesetze über Airflow, und der
Streamlit-Chat antwortet mit Quellen.

**Dateien, in dieser Reihenfolge:**
1. `.dockerignore`, `Dockerfile` (API)
2. `db/init/00_airflow_db.sh`
3. `airflow/Dockerfile`, `airflow/dags/consumer_law_ingest.py`
4. `app/__init__.py`, `app/client.py`, `app/streamlit_app.py`, `app/Dockerfile`
5. `docker-compose.yml`
6. `scripts/trigger_ingest.sh`, `Makefile` (`up`, `down`, `ingest`, `logs`, `ps`)
7. `src/rag/ingest/discover.py` (CLI), `src/rag/process/embed.py` (Kompatibilität),
   `tests/unit/test_app_client.py`, `tests/unit/test_discover.py`

**Was der Code leisten muss:**
- API-Image: Multi-Stage-Build mit uv, Torch nur für CPU, Nicht-Root-User, Modell-Cache in einem
  Volume.
- Airflow (aktuelle stabile Version und deren Doku prüfen: `api-server`, `dag-processor`,
  `scheduler`, Auth-Manager). Das Projekt im Airflow-Image in ein eigenes venv installieren, damit
  sich seine Abhängigkeiten nicht mit denen von Airflow beißen.
- DAG: täglich; zuerst ein Task, der die Quellen prüft, dann ein Task pro Gesetz (aus einer
  Umgebungsvariable), der die Pipeline-CLI aufruft; ein fehlschlagendes Gesetz darf die anderen
  nicht überspringen lassen.
- Compose: Healthchecks, Speicherlimits passend zu ca. 5 GB, benannte Volumes, ein Postgres für
  den Index und die Metadaten-DB von Airflow.
- Streamlit: Chat-Seite mit Quellen und Hinweis; eine Seitenleiste zur Wahl des Suchmodus.
- `trigger_ingest.sh`: warten, bis der DAG geparst ist, ihn auslösen, bis zum Ende pollen, die
  Zeilen aus `ingest_runs` ausgeben.

**Grüne Tests:** `make lint`, `make test`; von Hand: `make up && make ingest`, dann eine Frage unter
http://localhost:8501.

**Git:**
```bash
git checkout -b phase/5-runtime
git commit -m "Runtime: Docker images, compose stack, Airflow DAG and Streamlit UI"
git checkout main && git merge --no-ff phase/5-runtime -m "Merge phase 5: runtime stack"
```
**Vergleichen mit:** `87989e9` (Merge `b00b7e8`)

**Verständnisfragen:**
1. Warum laufen die Ingest-Tasks auf dieser Hardware nacheinander und nicht parallel?
2. Was passiert im DAG, wenn der Download des TKG fehlschlägt, die anderen aber klappen?

---

## Schritt 6 – Evaluation

**Ziel:** die Retrieval-Qualität mit echten Zahlen messen und den Standard-Suchmodus anhand der
Daten festlegen.

**Dateien, in dieser Reihenfolge:**
1. `evaluation/__init__.py`, `evaluation/questions.jsonl`
2. `evaluation/run_eval.py`
3. `tests/integration/test_evaluation.py`
4. `Makefile` (`eval`), `src/rag/config.py`, `.env.example`
5. `app/streamlit_app.py` (Evaluationsseite), API-Endpunkt `/evaluation`
6. `evaluation/results/*.json` (aus einem echten Lauf), `docs/evaluation.md`,
   `docs/decisions/0006-retrieval-strategy.md`

**Was der Code leisten muss:**
- Mindestens 30 deutsche Fragen in Verbrauchersprache mit erwartetem Gesetz + Paragraph(en). Jeden
  erwarteten Paragraphen am amtlichen Text und an den indexierten Bereichen prüfen.
- Gefundene Chunks vor der Bewertung zu eindeutigen Paragraphen zusammenfassen (sonst sind
  Strategien mit mehr Chunks benachteiligt). Hit-Rate@1/3/5/10 und MRR pro Variante berechnen.
- Varianten: Vektor / Volltext / Hybrid × Paragraph / Absatz, dazu Hybrid mit Reranking.
- Jedes Ergebnis als JSON speichern, mit Zeitstempel, Git-SHA, Index-Konfiguration und Rang pro
  Frage.
- Ein Quality-Gate-Modus: `--only-indexed`, `--gate-variant`, `--min-hit-rate`; Exit-Code 1 unter
  der Schwelle *und* wenn keine Frage beantwortbar ist.
- Den Absatz-Index neben dem Paragraph-Index mit `--no-activate` bauen.
- Aufschreiben, was du herausgefunden hast, und daraus den Standardmodus ableiten (hier: Vektor,
  ADR 0006).

**Grüne Tests:** `tests/integration/test_evaluation.py`, `tests/unit/test_download.py`.

**Git:**
```bash
git checkout -b phase/6-evaluation
git commit -m "Evaluation: 45 German test questions, Hit-Rate@k/MRR, six retrieval variants"
git checkout main && git merge --no-ff phase/6-evaluation -m "Merge phase 6: evaluation"
```
**Vergleichen mit:** `6ca84eb` (Merge `eab6be3`)

**Verständnisfragen:**
1. Warum kann die Volltextsuche die Hybrid-Suche hier *schlechter* machen als reine Vektorsuche?
2. Warum muss das Gate fehlschlagen, wenn null Fragen beantwortbar sind?

---

## Schritt 7 – Monitoring

**Ziel:** Prometheus fragt die API ab, Grafana zeigt ein Dashboard, und ein Alarm schlägt an, wenn
die Evaluation schlechter wird.

**Dateien, in dieser Reihenfolge:**
1. `monitoring/prometheus.yml`
2. `monitoring/alerts.yml`
3. `monitoring/grafana/provisioning/datasources/prometheus.yml`
4. `monitoring/grafana/provisioning/dashboards/dashboards.yml`
5. `monitoring/grafana/dashboards/rag-overview.json`
6. `docker-compose.yml` (prometheus, grafana), `.env.example`

**Was der Code leisten muss:**
- Die API exportiert das letzte *und* das vorletzte Evaluationsergebnis pro Variante als Gauges
  (Schritt 4/6), dazu die Schwelle. So brauchen die Alarmregeln keine fest eingetragenen Zahlen.
- Alarme: Evaluation unter der Schwelle, Regression gegenüber dem vorigen Lauf, API down,
  Fehlerrate, Latenz. Mit `promtool check rules` prüfen.
- Grafana: Datenquelle und Dashboard aus Dateien provisionieren (feste `uid`), ohne Klicken.

**Grüne Tests:** `make lint`, `make test`; von Hand: http://localhost:9090/alerts zeigt die Regeln,
http://localhost:3000 das Dashboard.

**Git:**
```bash
git checkout -b phase/7-monitoring
git commit -m "Monitoring: Prometheus scraping, eval and API alerts, Grafana dashboard"
git checkout main && git merge --no-ff phase/7-monitoring -m "Merge phase 7: monitoring"
```
**Vergleichen mit:** `6cf906a` (Merge `eaecb3b`)

**Verständnisfragen:**
1. Warum wird das Evaluationsergebnis über die API bereitgestellt, statt es an Prometheus zu pushen?
2. Warum unterscheidet sich die Alarmschwelle (0,65 auf 45 Fragen) von der CI-Schwelle (0,70 auf 27)?

---

## Schritt 8 – Fehlerszenarien und Runbook

**Ziel:** die vier Fehlerfälle am laufenden Stack vorführen und den Betrieb dokumentieren.

**Dateien, in dieser Reihenfolge:**
1. `scripts/_scenario.py`
2. `scripts/scenario_law_changed.py`
3. `scripts/scenario_paragraph_repealed.py`
4. `scripts/scenario_broken_xml.py`
5. `scripts/scenario_duplicate_ingest.py`
6. `Makefile` (`scenarios`), `docs/runbook.md`

**Was der Code leisten muss:**
- Mit einer eigenen Kopie eines kleinen Gesetzes unter eigenem Kürzel arbeiten, nie einen neuen
  Index aktivieren und danach aufräumen (Fremdschlüssel beachten: von unten nach oben löschen).
- Jedes Szenario verändert das XML so, wie es eine Änderung an der Quelle tun würde, ingestet erneut
  und prüft das Ergebnis mit ausdrücklichen OK/FAIL-Zeilen (Exit-Code 1 bei FAIL).
- Runbook: Dienste und URLs, täglicher Betrieb, typische Start- und Ingest-Probleme,
  Neuindizierung, Alarme, Lineage, Zurücksetzen.

**Grüne Tests:** `make lint`, `make test`, `make scenarios` (alles OK).

**Git:**
```bash
git checkout -b phase/8-scenarios
git commit -m "Failure scenarios: law changed, paragraph repealed, broken XML, duplicate ingest; runbook"
git checkout main && git merge --no-ff phase/8-scenarios -m "Merge phase 8: failure scenarios"
```
**Vergleichen mit:** `a866223` (Merge `71349ac`)

**Verständnisfragen:**
1. Warum ist im Szenario mit kaputtem XML die alte Version danach noch durchsuchbar?
2. In welche Tabellen schreibt ein zweiter, identischer Ingest, und in welche nicht?

---

## Schritt 9 – CI/CD

**Ziel:** Jeder Push führt Lint, Tests und das Evaluation-Gate aus; ein grünes `main`
veröffentlicht Images in GHCR.

**Dateien, in dieser Reihenfolge:**
1. `.github/workflows/ci.yml`
2. `.github/workflows/cd.yml`
3. `.github/dependabot.yml`

**Was der Code leisten muss:**
- CI-Jobs: `lint`; `test` (mit dem Extra `ml`, damit der Test mit dem echten Modell läuft,
  Modell-Cache über `actions/cache`); `eval-gate`: pgvector und MinIO mit `docker run` starten, die
  Fixture-Gesetze von der Platte ingesten, die Evaluation mit `--only-indexed` ausführen und unter
  der Schwelle fehlschlagen. Die Schwelle aus einem echten Lauf genau dieses Jobs ableiten, nicht
  raten.
- CD: ausgelöst durch einen erfolgreichen CI-Lauf auf `main` (`workflow_run`), API- und
  Streamlit-Image mit `GITHUB_TOKEN` bauen und pushen (`packages: write`).
- Dependabot für uv, GitHub Actions, Dockerfiles und Compose.
- Das Repository anlegen und nur `main` pushen:
  `gh repo create <user>/proj4-consumer-rights-rag --private --source . --remote origin`.

**Grüne Tests:** der CI-Lauf auf GitHub (alle drei Jobs), danach der CD-Lauf.

**Git:**
```bash
git checkout -b phase/9-ci-cd
git commit -m "CI/CD: lint, tests, eval quality gate; GHCR image publishing; Dependabot"
git checkout main && git merge --no-ff phase/9-ci-cd -m "Merge phase 9: CI/CD"
git push -u origin main
```
**Vergleichen mit:** `ec5e7fb` (Merge `c251a4f`)

**Verständnisfragen:**
1. Warum läuft das Gate auf einem kleinen Fixture-Set statt auf allen fünf Gesetzen?
2. Warum wird CD über `workflow_run` ausgelöst statt über einen eigenen `push`-Trigger?

---

## Schritt 10 – README und Rebuild-Guide

**Ziel:** ein README, das ein Recruiter auf der ersten Bildschirmseite versteht, und dieser Guide.

**Dateien, in dieser Reihenfolge:**
1. `README.md`
2. `docs/runbook.md` (Korrekturen)
3. `docs/REBUILD_GUIDE.md`

**Was der Code leisten muss:**
- Erste Bildschirmseite: die Frage in einem Satz, CI-Badge, ein deutlicher Hinweis „keine
  Rechtsberatung“, ein Mermaid-Architekturdiagramm, die Evaluationstabelle aus echten
  Ergebnissen, der Quickstart.
- Danach: Funktionsweise, „What happens when…“, Design-Entscheidungen (Links zu den ADRs),
  Grenzen.
- Jede Zahl im README muss aus einem echten Lauf stammen (`docs/evaluation.md`, `ingest_runs`).

**Grüne Tests:** `make lint`, `make test`, CI grün nach dem Push; das Mermaid-Diagramm wird auf
GitHub dargestellt.

**Git:**
```bash
git checkout -b phase/10-docs
git commit -m "README: architecture, evaluation results, quickstart, what-happens-when, limitations"
git commit -m "Rebuild guide derived from the Git history"
git checkout main && git merge --no-ff phase/10-docs -m "Merge phase 10: documentation"
git push
```
**Vergleichen mit:** `47a453c` (README); der Guide-Commit folgt danach auf `main`.

**Verständnisfragen:**
1. Welche drei Dinge sollte jemand wissen, der nur die erste Bildschirmseite des README liest?
2. Welche Grenze des Projekts würdest du im Interview zuerst nennen, und warum?
