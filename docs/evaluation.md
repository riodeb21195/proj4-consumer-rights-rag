# Evaluation

Wie gut findet das Retrieval die Vorschrift, die die Frage eines Verbrauchers beantwortet?

## Aufbau

- **Fragen:** 45 deutsche Fragen in `evaluation/questions.jsonl`, so formuliert, wie Verbraucher
  fragen („Wer zahlt das Porto für die Rücksendung …?“), nicht in Gesetzessprache. Zu jeder Frage
  sind das erwartete Gesetz und die erwarteten Paragraphen angegeben. Die erwarteten Paragraphen
  wurden am amtlichen Text geprüft (vorhanden, nicht aufgehoben, innerhalb der konfigurierten
  BGB-Bereiche); die Fragen selbst hat der Autor dieses Projekts geschrieben, sie stammen nicht aus
  einem externen Benchmark.
- **Korpus:** BGB (Verbraucherteile), EVO, PAngV, EnWG, TKG mit Stand vom 18.11.2026:
  1.022 Vorschriften, 1.751 Chunks (`paragraph`) / 3.649 Chunks (`absatz`).
- **Modell:** `intfloat/multilingual-e5-small` auf der CPU.
- **Metriken:** Die gefundenen Chunks werden in Rangfolge auf eindeutige (Gesetz, Paragraph)
  reduziert. *Hit-Rate@k* = Anteil der Fragen, bei denen ein erwarteter Paragraph unter den ersten k
  ist; *MRR* = Mittelwert von 1/Rang des ersten erwarteten Paragraphen (0, wenn keiner unter den
  ersten 30 Chunks ist).
- **Ausführen:** `make eval` (Ergebnisse: `evaluation/results/<zeitstempel>_<variante>.json`,
  inklusive Git-SHA, Index-Konfiguration und Rang pro Frage).

## Ergebnisse (18.11.2026, Git `b00b7e8`, 45 Fragen)

| Variante | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR |
|---|---:|---:|---:|---:|---:|
| **vector-paragraph** (Standard) | 0,42 | 0,64 | **0,71** | 0,82 | 0,55 |
| vector-absatz | 0,42 | 0,60 | 0,71 | 0,84 | 0,55 |
| fulltext-paragraph | 0,13 | 0,20 | 0,36 | 0,47 | 0,22 |
| hybrid-paragraph (RRF) | 0,38 | 0,53 | 0,62 | 0,76 | 0,49 |
| hybrid-absatz (RRF) | 0,38 | 0,53 | 0,62 | 0,78 | 0,49 |
| hybrid-paragraph + Cross-Encoder-Reranking | 0,51 | 0,78 | 0,82 | 0,87 | 0,65 |

Reranking-Modell: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, 30 Kandidaten pro Frage.
Der Reranking-Lauf brauchte für 45 Fragen 20 Min. 22 s (≈ 27 s pro Frage) auf der Intel-CPU von
2019; die anderen Varianten brauchen deutlich unter einer Sekunde pro Frage.

## Erkenntnisse

1. **Lexikalische Suche scheitert am Alltagswortschatz.** Verbraucher sagen „Porto“,
   „Handyvertrag“, „Kaution“; das Gesetz sagt „Kosten der Rücksendung“, „öffentlich zugängliche
   Telekommunikationsdienste“, „Mietsicherheit“. Die Volltextsuche (Postgres-Konfiguration
   `german`, OR-Query über alle Wörter der Frage, `ts_rank_cd`) erreicht nur 0,36 Hit@5. Sie
   bevorzugt lange Vorschriften mit vielen allgemeinen Wörtern (z. B. taucht TKG § 112 bei Fragen
   auf, die nichts damit zu tun haben).
2. **Hybrid-Fusion schadet deshalb.** RRF gibt dem schwachen Volltext-Ranking dasselbe Gewicht wie
   dem Vektor-Ranking: Hit@5 sinkt von 0,71 auf 0,62. Zwei Folgeexperimente (nicht als Varianten
   committet, Zahlen aus einmaligen Läufen auf denselben Fragen):
   - Das Volltext-Ranking in RRF mit 0,5 / 0,3 / 0,2 zu gewichten ergab Hit@5 0,62 / 0,67 / 0,67,
     nie besser als reine Vektorsuche;
   - ein IDF-gewichteter Volltext-Score (BM25-ähnlich, seltene Wörter zählen mehr) verbesserte den
     Volltext allein nur von 0,38 auf 0,40 Hit@5.
3. **Die Chunking-Strategie spielt hier kaum eine Rolle.** `paragraph` und `absatz` liefern
   dasselbe Hit@5; `absatz` ist bei Hit@10 etwas besser, verdoppelt aber die Zahl der Chunks und
   die Embedding-Zeit. `paragraph` bleibt Standard.
4. **Ein Cross-Encoder-Reranker ist klar am besten** (+0,11 Hit@5, +0,10 MRR gegenüber reiner
   Vektorsuche), aber mit ≈ 27 s pro Frage auf dieser Hardware nicht interaktiv nutzbar.

**Entscheidung:** Die API nutzt standardmäßig `vector`-Retrieval auf dem `paragraph`-Index;
Hybrid- und Volltextsuche bleiben wählbar (`RAG_RETRIEVAL_MODE`, Seitenleiste der UI) und werden
bei jedem Lauf mitbewertet; Reranking ist optional (`RAG_RERANK_ENABLED=true`) für Rechner mit mehr
CPU/GPU. Siehe ADR 0006.

## Wo die Standardvariante scheitert

Fragen, die `vector-paragraph` nicht in den Top 5 beantwortet (Rang des erwarteten Paragraphen,
Rang nach Reranking):

| Frage | Erwartet | Rang | Reranking |
|---|---|---:|---:|
| Wie lange habe ich Zeit, einen online gekauften Artikel zurückzugeben …? | § 355 / § 356 BGB | 28 | 10 |
| Bei welchen Bestellungen gibt es kein Widerrufsrecht …? | § 312g BGB | 10 | 1 |
| Welche Informationen muss mir ein Onlineshop vor der Bestellung geben? | § 312d BGB | 7 | 11 |
| Darf ein Händler eine Extragebühr für Kreditkarte oder PayPal berechnen? | § 312a BGB | – | – |
| Wann hat eine gekaufte Sache rechtlich einen Mangel? | § 434 BGB | 12 | 17 |
| Kann ich wählen, ob repariert wird oder ich ein neues Gerät bekomme? | § 439 BGB | 18 | 2 |
| Kann ich weniger bezahlen, wenn die Ware einen Mangel hat …? | § 441 BGB | – | – |
| Wann kann ich ohne Fristsetzung vom Kaufvertrag zurücktreten? | § 440 / § 323 BGB | 12 | 2 |
| Muss ich beweisen, dass der Mangel schon beim Kauf vorhanden war …? | § 477 BGB | 8 | 1 |
| Darf ein Händler die Gewährleistung ausschließen? | § 476 BGB | 19 | 21 |
| Wie viele Monatsmieten darf der Vermieter als Kaution verlangen? | § 551 BGB | 7 | 1 |
| Darf ich die Miete kürzen, wenn die Heizung ausfällt? | § 536 BGB | – | 17 |
| Kann ich einen Ratenkredit noch widerrufen? | § 495 / § 356b BGB | 9 | 5 |

Typische Ursachen: Nachbarvorschriften mit demselben Vokabular (§§ 435–438 rund um § 434,
§§ 559 ff. „Mieterhöhung nach Modernisierung“ bei einer Frage zur Mietminderung) und Umschreibungen
ohne gemeinsame Wörter („Extragebühr“ vs. „Entgelt für die Nutzung eines Zahlungsmittels“).

## Quality Gate und Alarme

- **CI** (`.github/workflows/ci.yml`, Job `eval-gate`) indexiert das committete Fixture-Set (EVO,
  PAngV, gekürztes BGB) mit dem echten Modell und bewertet die 27 Fragen, die damit beantwortbar
  sind (`--only-indexed`). Ein lokaler Lauf genau dieses Jobs am 18.11.2026 ergab für
  `vector-paragraph` Hit@5 = 0,74 (20/27), `hybrid-paragraph` 0,67, `fulltext-paragraph` 0,48.
  **Schwelle: 0,70** – der Build schlägt fehl, sobald mehr als eine der 27 Fragen verloren geht.
- **Prometheus-Alarm** `RagEvalBelowThreshold` nutzt `RAG_EVAL_HIT_RATE_THRESHOLD = 0,65` auf dem
  vollen Set (heute 0,71 = 32/45; schlägt an, wenn mehr als zwei Fragen verloren gehen).
  `RagEvalRegression` schlägt an, wenn Hit@5 einer Variante um mehr als 2 Punkte gegenüber dem
  vorigen Lauf fällt.

## Grenzen

- 45 Fragen sind eine kleine Stichprobe: Eine Frage verschiebt Hit@k um 2,2 Punkte.
- Es gibt kein Held-out-Set. Die Experimente mit Fusionsgewichten und IDF wurden auf denselben
  Fragen gemessen, an denen sie bewertet würden – ein weiterer Grund, sie nicht zu übernehmen.
- Fragen und erwartete Paragraphen stammen von einem Autor; mehrere Vorschriften können richtige
  Antworten sein, gezählt werden nur die angegebenen.
