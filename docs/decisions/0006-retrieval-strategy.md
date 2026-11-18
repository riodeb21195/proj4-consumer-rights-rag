# 0006 – Retrieval: Vektorsuche als Standard, Hybrid und Reranking optional

- Status: angenommen
- Datum: 18.11.2026

## Kontext
Die Spezifikation verlangt Hybrid-Suche (Vektor + Volltext) mit optionalem, begründetem Reranking.
Alle drei Retrieval-Modi und ein Cross-Encoder-Reranker sind umgesetzt
(`src/rag/retrieval/search.py`, `rerank.py`): Die Hybrid-Suche führt das Vektor- und das
Postgres-Volltext-Ranking mit Reciprocal Rank Fusion (k = 60) zusammen. Dafür muss man
Cosinus-Ähnlichkeit und `ts_rank_cd` nicht aufeinander abstimmen.

Die Evaluation mit 45 Verbraucherfragen (`docs/evaluation.md`, 18.11.2026) ergab:

| Variante | Hit@5 | MRR | Latenz pro Frage (CPU) |
|---|---:|---:|---|
| Vektor | 0,71 | 0,55 | < 1 s |
| Volltext | 0,36 | 0,22 | < 1 s |
| Hybrid (RRF) | 0,62 | 0,49 | < 1 s |
| Hybrid + Reranking | 0,82 | 0,65 | ≈ 27 s |

Die Volltextsuche scheitert am Unterschied zwischen Alltags- und Rechtssprache; mischt man sie dazu,
sinkt die Qualität. Weder eine geringere Gewichtung in RRF (0,5 / 0,3 / 0,2) noch ein IDF-gewichteter
Volltext-Score waren besser als reine Vektorsuche.

## Entscheidung
- Standard `RAG_RETRIEVAL_MODE=vector`.
- Hybrid- und Volltextsuche bleiben pro Anfrage wählbar (`mode` in `/search` und `/ask`,
  Seitenleiste der UI) und sind Teil jedes Evaluationslaufs. So kann eine bessere
  Volltextkomponente oder ein anderer Korpus die Entscheidung mit Daten ändern.
- Reranking bleibt optional (`RAG_RERANK_ENABLED`, standardmäßig aus): beste Qualität, aber
  ca. 27 s pro Frage auf einer Intel-CPU von 2019 sind für eine Chat-Oberfläche nicht akzeptabel.

## Konsequenzen
- Der Standardweg ist der schnellste und auf diesem Fragenset auch der genaueste.
- Mit GPU oder schnellerer CPU ist Reranking der erste Hebel (+0,11 Hit@5).
- Besseres lexikalisches Retrieval (Synonymwörterbuch für Alltagsbegriffe, BM25-Erweiterung wie
  ParadeDB/pg_search) würde eine neue Bewertung der Hybrid-Suche lohnend machen.
