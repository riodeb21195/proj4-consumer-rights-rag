# Evaluation

How well does retrieval find the provision that answers a consumer's question?

## Setup

- **Questions:** 45 German questions in `evaluation/questions.jsonl`, phrased the way consumers ask
  ("Wer zahlt das Porto für die Rücksendung …?"), not in statutory language. Each lists the
  expected law + paragraph(s). The expected paragraphs were checked against the official text
  (existence, not repealed, inside the configured BGB ranges); the questions themselves were
  written by the author of this project, not taken from an external benchmark.
- **Corpus:** BGB (consumer parts), EVO, PAngV, EnWG, TKG as of 2026-11-18:
  1,022 provisions, 1,751 chunks (`paragraph`) / 3,649 chunks (`absatz`).
- **Model:** `intfloat/multilingual-e5-small` on CPU.
- **Metrics:** retrieved chunks are collapsed to distinct (law, paragraph) in rank order.
  *Hit-Rate@k* = share of questions with an expected paragraph among the first k;
  *MRR* = mean of 1/rank of the first expected paragraph (0 if none in the top 30 chunks).
- **Run:** `make eval` (results: `evaluation/results/<timestamp>_<variant>.json`, including the
  git SHA, index config and the rank per question).

## Results (2026-11-18, git `b00b7e8`, 45 questions)

| Variant | Hit@1 | Hit@3 | Hit@5 | Hit@10 | MRR |
|---|---:|---:|---:|---:|---:|
| **vector-paragraph** (default) | 0.42 | 0.64 | **0.71** | 0.82 | 0.55 |
| vector-absatz | 0.42 | 0.60 | 0.71 | 0.84 | 0.55 |
| fulltext-paragraph | 0.13 | 0.20 | 0.36 | 0.47 | 0.22 |
| hybrid-paragraph (RRF) | 0.38 | 0.53 | 0.62 | 0.76 | 0.49 |
| hybrid-absatz (RRF) | 0.38 | 0.53 | 0.62 | 0.78 | 0.49 |
| hybrid-paragraph + cross-encoder rerank | 0.51 | 0.78 | 0.82 | 0.87 | 0.65 |

Rerank model: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, 30 candidates per question.
The rerank run took 20 min 22 s for 45 questions (≈ 27 s per question) on the 2019 Intel CPU;
the other variants need well under a second per question.

## Findings

1. **Lexical search fails on lay vocabulary.** Consumers say "Porto", "Handyvertrag",
   "Kaution"; the law says "Kosten der Rücksendung", "öffentlich zugängliche
   Telekommunikationsdienste", "Mietsicherheit". Full-text search (Postgres `german` config,
   OR-query over all question terms, `ts_rank_cd`) reaches only 0.36 Hit@5. It favours long
   provisions that contain many common words (e.g. TKG § 112 appears for unrelated questions).
2. **Hybrid fusion therefore hurts.** RRF gives the weak full-text ranking the same say as the
   vector ranking: Hit@5 drops from 0.71 to 0.62. Two follow-up experiments (not committed as
   variants, numbers from one-off runs on the same questions):
   - weighting the full-text list in RRF with 0.5 / 0.3 / 0.2 gave Hit@5 0.62 / 0.67 / 0.67,
     never better than pure vector search;
   - an IDF-weighted full-text score (BM25-like, rare terms count more) improved full-text
     alone only from 0.38 to 0.40 Hit@5.
3. **Chunking strategy barely matters here.** `paragraph` and `absatz` give the same Hit@5;
   `absatz` is slightly better at Hit@10 but doubles the number of chunks and embedding time.
   `paragraph` stays the default.
4. **A cross-encoder reranker is clearly best** (+0.11 Hit@5, +0.10 MRR over pure vector), but
   at ~27 s per question it is not usable interactively on this hardware.

**Decision:** the API defaults to `vector` retrieval on the `paragraph` index; hybrid and
full-text search stay selectable (`RAG_RETRIEVAL_MODE`, UI sidebar) and are evaluated on every
run; reranking is optional (`RAG_RERANK_ENABLED=true`) for machines with more CPU/GPU.
See ADR 0006.

## Where the default variant fails

Questions not answered within the top 5 by `vector-paragraph` (rank of the expected paragraph,
rank after reranking):

| Question | Expected | Rank | Rerank |
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

Typical causes: neighbouring provisions that use the same vocabulary (§§ 435–438 around § 434,
§§ 559 ff. "Mieterhöhung nach Modernisierung" for a question about reducing rent) and
paraphrases with no lexical overlap ("Extragebühr" vs. "Entgelt für die Nutzung eines
Zahlungsmittels").

## Quality gate and alerting

- **CI** (`.github/workflows/ci.yml`, job `eval-gate`) indexes the committed fixture set
  (EVO, PAngV, trimmed BGB) with the real model and evaluates the 27 questions answerable from
  it (`--only-indexed`). A local run of exactly this job on 2026-11-18 gave `vector-paragraph`
  Hit@5 = 0.74 (20/27), `hybrid-paragraph` 0.67, `fulltext-paragraph` 0.48.
  **Threshold: 0.70** — the build fails as soon as more than one of the 27 questions is lost.
- **Prometheus alert** `RagEvalBelowThreshold` uses `RAG_EVAL_HIT_RATE_THRESHOLD = 0.65` on the full
  set (0.71 = 32/45 today; fires when more than two questions are lost).
  `RagEvalRegression` fires when Hit@5 of any variant drops by more than 2 points against the
  previous run.

## Limitations

- 45 questions are a small sample: one question moves Hit@k by 2.2 points.
- There is no held-out set. The fusion-weight and IDF experiments above were measured on the
  same questions they would be judged on, which is one more reason they were not adopted.
- Questions and expected paragraphs come from one author; several provisions can be valid
  answers, only the listed ones count as hits.
