# 0003 – Postgres + pgvector als einziger Index

- Status: angenommen
- Datum: 18.11.2026

## Kontext
Wir brauchen Vektorsuche, deutsche Volltextsuche, Metadaten, Versionierung und Lineage. Der Korpus
ist klein (einige tausend Chunks).

## Entscheidung
Eine Postgres-17-Datenbank mit der Extension pgvector (Image `pgvector/pgvector:0.8.7-pg17`):

- `chunks.embedding vector(384)` mit einem HNSW-Index (Cosinus),
- `chunks.tsv` als generierter `tsvector` mit der Konfiguration `german` und einem GIN-Index,
- relationale Tabellen für Läufe, Gesetzesversionen, Normen, Index-Konfigurationen und das
  Antwort-Log.

Eine eigene Vektordatenbank (Qdrant, Weaviate, …) wurde nicht gewählt: Sie würde Metadaten doppelt
halten, einen zweiten Konsistenzmechanismus brauchen und einen weiteren Container auf einem Rechner
mit wenig RAM.

## Konsequenzen
- Hybrid-Suche ist reines SQL; der Ingest pro Gesetz ist eine einzige ACID-Transaktion (Index und
  Metadaten können nie auseinanderlaufen).
- Lineage ist ein Join: answer_log -> chunks -> norms -> law_versions -> Roh-XML in MinIO.
- HNSW mit einem Filter `WHERE index_config_id = ...` nutzt die iterativen Scans von pgvector
  (>= 0.8), damit kein Recall verloren geht, wenn mehrere Index-Konfigurationen nebeneinander
  existieren.
