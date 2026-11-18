# 0002 – Embedding-Modell: intfloat/multilingual-e5-small

- Status: angenommen
- Datum: 18.11.2026

## Kontext
Deutscher Text, nur CPU (Intel-MacBook von 2019, keine GPU), begrenzter RAM, keine bezahlten APIs.

## Entscheidung
`intfloat/multilingual-e5-small` über sentence-transformers:

- mehrsprachig inkl. Deutsch, 384 Dimensionen, 512-Token-Fenster (im Container geprüft:
  `get_sentence_embedding_dimension() == 384`, `max_seq_length == 512`),
- klein genug für die CPU: ca. 0,11 s pro längerer Passage auf der Intel-CPU von 2019 in Docker
  (64 Passagen mit ca. 600 Zeichen in 7,2 s, gemessen am 18.11.2026),
- nutzt die Präfixe `query: ` / `passage: `, umgesetzt in `SentenceTransformerEmbedder`.

`paraphrase-multilingual-MiniLM-L12-v2` wurde geprüft; seine Grenze von 128 Tokens hätte die meisten
Paragraphen abgeschnitten.

## Konsequenzen
- Der Modellname ist Teil der Index-Konfiguration: Ein Modellwechsel löst eine vollständige
  Neuindizierung aus.
- Der Spaltentyp ist `vector(384)`; ein Modell mit anderer Dimension braucht eine Schema-Migration.
- In Tests wird ein deterministischer `FakeEmbedder` (Hashing-Trick) genutzt, damit sie ohne
  PyTorch laufen.
