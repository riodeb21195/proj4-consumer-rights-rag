# Projekt 4: RAG Pipeline – German Consumer Rights

Du baust ein produktionsreifes Data-Engineering-Portfolio-Projekt von Grund auf in diesem (leeren) Repository. Programmiere alles selbst: Code, Konfiguration, Tests, CI/CD, Doku. Der Schwerpunkt liegt auf der Daten-Pipeline für KI, nicht auf dem Modell.

## Arbeitsweise
1. Lies diese Spezifikation komplett. Erstelle zuerst einen Plan (Phasen, Dateien, Risiken) und warte auf meine Freigabe.
2. Baue in Phasen. Nach jeder Phase: `make lint` und `make test` müssen grün sein, dann ein Git-Commit mit aussagekräftiger Message.
3. Prüfe Download-URLs, XML-Format und aktuelle Tool-Versionen, indem du die echten Quellen und Dokus abrufst. Nicht raten.
4. Erfinde keine Zahlen. Evaluationsergebnisse im README nur aus echten Läufen.
5. Bei Unklarheiten oder Entscheidungen, die Geld kosten: mich fragen.
6. Erkläre wichtige Entscheidungen (Chunking, Embedding-Modell, Vektor-DB) kurz in `docs/decisions/` (ADR-Format).
7. Erstelle am Ende des Projekts `docs/REBUILD_GUIDE.md`: eine Schritt-für-Schritt-Anleitung, mit der ich das Projekt in einem leeren Repo selbst nachbauen kann. Leite die Schritte aus der tatsächlichen Git-Historie dieses Repos ab. Pro Schritt: Ziel in einem Satz; die Dateien in der Reihenfolge, in der ich sie anlege; was der Code leisten muss, mit Hinweisen, aber ohne fertige Lösung; welche Tests danach grün sein müssen (die Tests darf ich aus diesem Repo übernehmen); die Git-Befehle (Branch anlegen, Commit-Message, Merge); der Commit-Hash dieses Repos zum Vergleichen; 1–2 Verständnisfragen. Dieses Repo ist meine private Musterlösung, die Anleitung wird normal mit committet (nicht in die .gitignore).

## Rahmenbedingungen
- Hardware: Intel-MacBook von 2019, RAM begrenzt, keine GPU. Kleines, mehrsprachiges Embedding-Modell auf CPU. Lokales LLM über Ollama nur als optionales Compose-Profil, Retrieval muss auch ohne LLM funktionieren.
- Alles läuft lokal mit `make up`. Keine Cloud-Kosten, keine bezahlten APIs.
- Python 3.12, Abhängigkeiten mit uv.
- Code, Kommentare und README auf Englisch; Daten und Testfragen auf Deutsch.

## Qualitätsstandard
- `.gitignore` von Anfang an, mindestens: .env, heruntergeladene Gesetzes-XML, Modell-Caches (z. B. Hugging Face), Python-Caches, .venv, IDE-Dateien. Vor jedem Commit prüfen, dass keine Secrets oder großen Datendateien im Repo landen.
- Linting/Formatting: ruff, pre-commit
- Tests: pytest, Unit + Integration (testcontainers), Ziel über 80 % Coverage für `src/`
- Type Hints überall
- Idempotente Läufe
- Strukturierte JSON-Logs
- Makefile: `up`, `down`, `ingest`, `eval`, `test`, `lint`, `format`, `clean`
- README: Die erste Bildschirmseite enthält die Frage in einem Satz, ein Architekturdiagramm (Mermaid), die Evaluationsergebnisse und den Quickstart. Danach: Details, Abschnitt „What happens when…“, Design-Entscheidungen, Grenzen. Deutlicher Hinweis: Das Tool ersetzt keine Rechtsberatung.
- `docs/runbook.md`, `docs/evaluation.md`

## Ziel
Eine Pipeline hält deutsche Gesetzestexte aktuell und durchsuchbar. Fragen werden mit Quellenangabe (Gesetz + Paragraph) beantwortet.
**Leitfrage:** Was steht mir als Verbraucher rechtlich zu?

## Datenquelle (ohne Anmeldung)
- gesetze-im-internet.de, XML-Download pro Gesetz. Auswahl konfigurierbar, Start z. B. mit: BGB (verbraucherrelevante Teile), Eisenbahn-Verkehrsordnung (EVO), Preisangabenverordnung (PAngV), Energiewirtschaftsgesetz (EnWG), Telekommunikationsgesetz (TKG). Prüfe Verfügbarkeit und Format selbst.
- Gesetzestexte sind amtliche Werke und urheberrechtlich frei.

## Tech-Stack
- Storage: MinIO (Original-XML), Postgres + pgvector (Chunks, Embeddings, Metadaten)
- Orchestrator: Airflow (aktuelle stabile Version) für den inkrementellen Ingest
- Processing: Python, lxml, sentence-transformers (lokal, CPU)
- Retrieval: Hybrid-Suche (Vektor + Volltext) mit Reranking optional, begründet
- API: FastAPI
- UI: Streamlit (Chat mit Quellenangaben + Seite mit Evaluationsergebnissen)
- Monitoring: Prometheus-Metriken der API (Latenz, Fehler, Anfragen), Grafana, Alert bei schlechterer Evaluation

## Fachliche Anforderungen
**Ingest**
- Change Detection per Content-Hash: nur neue oder geänderte Gesetze/Paragraphen neu verarbeiten
- Entfernte Paragraphen werden aus dem Index gelöscht
- Lauf-Metadaten und Versionierung (welcher Stand eines Gesetzes ist indexiert)

**Processing**
- Chunking entlang der Gesetzesstruktur (Paragraph, Absatz), nicht blind nach Zeichen
- Metadaten pro Chunk: Gesetz, Paragraph, Überschrift, Stand, Quelle-URL
- Validierung: leere, zu lange, doppelte Chunks erkennen
- Chunking-Strategie und Embedding-Modell als Version gespeichert, Neuindizierung bei Wechsel

**Retrieval + Antwort**
- Antwort immer mit Quellenangabe; ohne LLM werden die relevantesten Paragraphen angezeigt
- Lineage: Gesetz → Chunk → Antwort nachvollziehbar

**Evaluation**
- Mindestens 30 Testfragen auf Deutsch mit erwartetem Gesetz/Paragraph in `evaluation/questions.jsonl`
- Metriken: Hit-Rate@k, MRR; Ergebnisse versioniert gespeichert und im README als Tabelle
- Vergleich mindestens zweier Varianten (z. B. Chunking-Strategien oder reine Vektor- vs. Hybrid-Suche)

## CI/CD (GitHub Actions)
- CI bei jedem Push und Pull Request: Linting, pytest, Evaluation als Quality Gate auf einem kleinen Gesetzes-Set (Build schlägt fehl, wenn Hit-Rate unter einen Schwellenwert fällt)
- CD auf main: Images für API und Streamlit zur GitHub Container Registry
- Dependabot, Status-Badge im README

## Fehlerszenarien zum Vorführen (`scripts/`)
- Gesetz wird geändert → nur betroffene Chunks neu, Rest unverändert
- Paragraph wird aufgehoben → verschwindet aus dem Index
- Kaputte XML-Datei → wird übersprungen und gemeldet, Pipeline läuft weiter
- Ingest doppelt ausgeführt → keine Duplikate

## Ordnerstruktur (Vorschlag, darfst du begründet anpassen)
```
proj4-consumer-rights-rag/
├── README.md
├── Makefile
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .github/
│   ├── workflows/ci.yml
│   ├── workflows/cd.yml
│   └── dependabot.yml
├── docs/
│   ├── decisions/
│   ├── REBUILD_GUIDE.md
│   ├── evaluation.md
│   └── runbook.md
├── airflow/dags/
├── db/init/
├── src/rag/
│   ├── config.py
│   ├── ingest/          # download, discover, hashing, parse_xml
│   ├── process/         # chunk, embed, validate
│   ├── store/           # vector_store
│   ├── retrieval/       # search, rerank, generate (optional)
│   └── api/             # FastAPI, metrics
├── evaluation/
│   ├── questions.jsonl
│   ├── run_eval.py
│   └── results/
├── app/                 # Streamlit
├── monitoring/
├── scripts/             # Fehlerszenarien
└── tests/
    ├── unit/
    └── integration/
```

## Fertig ist das Projekt, wenn
- `make up` + `make ingest` die Gesetze indexiert und die Streamlit-App Fragen mit Quellen beantwortet
- Evaluationsergebnisse mit echten Zahlen dokumentiert sind
- `make test` und `make lint` grün sind und CI inklusive Quality Gate grün ist
- README, ADRs und Runbook vollständig sind
