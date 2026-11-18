# Architektur

Wie die Daten von gesetze-im-internet.de bis zur Antwort fließen. Die Gründe dafür stehen in den
[ADRs](decisions/), der Betrieb im [Runbook](runbook.md), die Retrieval-Qualität in der
[Evaluation](evaluation.md).

## Datenquelle

[gesetze-im-internet.de](https://www.gesetze-im-internet.de) veröffentlicht jedes Bundesgesetz als
ZIP mit einer XML-Datei (`gii-norm.dtd`), z. B. `https://www.gesetze-im-internet.de/bgb/xml.zip`.
Gesetze sind amtliche Werke und urheberrechtsfrei (§ 5 UrhG). Die Auswahl steht in
`src/rag/config.py`:

| Gesetz | Kürzel | Umfang |
|---|---|---|
| Bürgerliches Gesetzbuch | `bgb` | §§ 13–14, 241–361, 433–480, 488–515, 535–580a, 631–651y (Verträge, Verbraucherverträge, Kauf, Verbraucherkredit, Miete, Werk- und Reiseverträge) |
| Eisenbahn-Verkehrsordnung | `evo_2023` | vollständig |
| Preisangabenverordnung | `pangv_2022` | vollständig |
| Energiewirtschaftsgesetz | `enwg_2005` | vollständig |
| Telekommunikationsgesetz | `tkg_2021` | vollständig |

Vor dem Ingest prüft der DAG jedes Kürzel gegen das offizielle Verzeichnis `gii-toc.xml`, weil
Gesetze unter neuen Kürzeln neu veröffentlicht werden (die EVO heißt `evo_2023`, nicht `evo`).

## Ingest (`src/rag/ingest/`, `airflow/dags/consumer_law_ingest.py`)

Der DAG läuft täglich, mit einem Task pro Gesetz. Die Change Detection arbeitet auf drei Ebenen,
sodass ein Tag ohne Änderungen eine HTTP-Anfrage pro Gesetz kostet:

1. **HTTP:** `If-None-Match` / `If-Modified-Since` → `304 Not Modified` beendet den Task.
2. **Datei:** SHA-256 des XML. Eine neue Datei wird in MinIO archiviert
   (`raw-laws/<slug>/<builddate>_<sha>.xml`) und als neue Zeile in `law_versions` festgehalten.
3. **Vorschrift:** ein Content-Hash pro Norm (Titel + Text). Nur neue oder geänderte Normen werden
   neu gechunkt und embedded; verschwundene oder als `(weggefallen)` markierte Normen werden samt
   ihren Chunks gelöscht.

Jedes Gesetz wird in einer Datenbanktransaktion verarbeitet: Ein Fehler lässt die vorherige Version
unberührt. Jeder Lauf steht mit Statistik und Fehlern pro Gesetz in `ingest_runs`.

## Verarbeitung (`src/rag/process/`)

- **Chunking** folgt der Gesetzesstruktur: ein Chunk pro Paragraph (`paragraph`, Standard; lange
  Paragraphen werden an Absatzgrenzen in Stücke von höchstens 2.000 Zeichen geteilt) oder einer pro
  Absatz (`absatz`). Ein Absatz, der allein zu lang ist, wird an Aufzählungen, dann an Satzenden
  geteilt. Dem eingebetteten Text werden Gesetz, Paragraph, Absatz, Überschrift und der
  umgebende Abschnittstitel vorangestellt.
- **Metadaten pro Chunk:** Gesetz, Paragraph, Absatz, Überschrift, Stand, Quell-URL (Deep Link auf
  den Paragraphen), Gesetzesversion; die Norm kennt außerdem ihren Gliederungspfad
  (Buch/Abschnitt/Titel).
- **Validierung:** Leere und doppelte Chunks werden verworfen, zu lange gemeldet.
- **Embedding:** `intfloat/multilingual-e5-small` (384 Dimensionen) auf der CPU.
- **Index-Versionierung:** Chunking-Strategie + Chunking-Version + Embedding-Modell bilden eine
  Zeile in `index_configs`. Ändert sich etwas davon, entsteht ein neuer Index neben dem alten; die
  API schaltet erst um, wenn der neue vollständig ist.

## Retrieval und Antworten (`src/rag/retrieval/`, `src/rag/api/`)

- `vector` (Standard): Cosinus-Suche auf einem HNSW-Index. `fulltext`: Postgres-Volltextsuche mit
  `german`. `hybrid`: Reciprocal Rank Fusion aus beiden. Optional Reranking mit einem
  Cross-Encoder.
- Ohne LLM liefert `/ask` die relevantesten Paragraphen mit Quellenangabe („§ 312g BGB“) und Links.
  Mit dem optionalen Ollama-Profil schreibt ein kleines lokales Modell eine Antwort nur auf Basis
  dieser Paragraphen; die Quellen hängen immer dran.
- **Lineage:** Jede Antwort wird in `answer_log` gespeichert. `GET /lineage/{answer_id}` liefert
  die Chunks, Gesetzesversionen, den Stand und den MinIO-Schlüssel des Roh-XMLs hinter der Antwort.

## Evaluation, Monitoring, CI/CD

- `make eval` führt alle Retrieval-Varianten über `evaluation/questions.jsonl` aus und speichert die
  Ergebnisse als versioniertes JSON (Git-SHA, Index-Konfiguration, Rang pro Frage) in
  `evaluation/results/`.
- Die API stellt Anfragenzahl, Latenz und Fehler sowie die letzten Evaluationsergebnisse als
  Prometheus-Metriken bereit. Grafana zeigt sie auf dem provisionierten Dashboard
  „Consumer Rights RAG“. Alarme: Evaluation unter der Schwelle, Verschlechterung gegenüber dem
  vorigen Lauf, API nicht erreichbar, Fehlerrate, Latenz (`monitoring/alerts.yml`).
- **CI** (bei jedem Push und Pull Request): ruff + mypy, Unit- und Integrationstests
  (testcontainers, Coverage-Gate 80 %) und ein **Evaluation-Quality-Gate**: Das committete
  Fixture-Set (gekürztes BGB, EVO, PAngV) wird mit dem echten Modell indexiert, und der Build
  schlägt fehl, wenn Hit@5 der Standardvariante unter 0,70 fällt.
- **CD** (main, nach grüner CI): API- und Streamlit-Images in die GitHub Container Registry.
  Dependabot hält Python-Pakete, Actions und Basis-Images aktuell.

## Was passiert, wenn…

| …das passiert | …macht die Pipeline das | Demo |
|---|---|---|
| ein Gesetz geändert wird | Nur die geänderten Paragraphen bekommen neue Chunks und Embeddings; alle anderen Chunks behalten ihre IDs. | `scripts/scenario_law_changed.py` |
| ein Paragraph aufgehoben wird | Er wird aus `norms` entfernt, und seine Chunks verschwinden aus dem Index. | `scripts/scenario_paragraph_repealed.py` |
| das heruntergeladene XML kaputt ist | Die Transaktion des Gesetzes wird zurückgerollt, die alte Version bleibt durchsuchbar, der Fehler steht in `ingest_runs`, und die anderen Gesetze laufen weiter. | `scripts/scenario_broken_xml.py` |
| der Ingest doppelt läuft | Der zweite Lauf findet dieselben Hashes und schreibt nichts; keine Duplikate. | `scripts/scenario_duplicate_ingest.py` |
| die Quelle nicht erreichbar ist | 3 Versuche pro Download, 1 Wiederholung durch Airflow; der Index liefert weiter die letzte Version. | – |
| ein Gesetz ein neues Kürzel bekommt | `check_sources` schlägt fehl, bevor etwas ingestet wird. | – |
| sich Chunking-Strategie oder Modell ändern | Ein neuer Index entsteht neben dem alten und wird aktiviert, sobald er vollständig ist. | [Runbook](runbook.md) |
| die Retrieval-Qualität sinkt | Die CI lässt den Build fehlschlagen; im laufenden Stack löst Prometheus `RagEvalBelowThreshold` / `RagEvalRegression` aus. | [Evaluation](evaluation.md) |

Die vier Demos laufen mit `make scenarios` gegen den laufenden Stack.

## Bekannte Einschränkungen

Zusätzlich zu denen im README:

- Eine Vorschrift im EnWG ergibt nur leere Chunks (von der Validierung verworfen); weil sie keinen
  Chunk hat, wird sie bei jedem Lauf erneut geprüft.
- Single-Node-Setup mit Standard-Zugangsdaten, gedacht für den lokalen Betrieb.
