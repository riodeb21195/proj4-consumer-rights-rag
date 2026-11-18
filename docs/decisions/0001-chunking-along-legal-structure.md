# 0001 – Chunking entlang der Gesetzesstruktur (§ / Absatz)

- Status: angenommen
- Datum: 18.11.2026

## Kontext
Nutzer fragen nach Rechten, die in bestimmten Vorschriften stehen („§ 355 BGB“). Antworten müssen
Gesetz und Paragraph nennen. Feste Zeichenfenster würden Absätze und Aufzählungen zerschneiden,
benachbarte Paragraphen in einem Chunk mischen und die Quellenangabe mehrdeutig machen.

Das XML von gesetze-im-internet.de bringt die Struktur schon mit: eine `<norm>` pro §, `<P>`-Elemente
pro Absatz und `DL/DT/DD` für Aufzählungen. Gemessen an den konfigurierten Gesetzen (18.11.2026):
Median-Länge eines § von 590 Zeichen (BGB) bis 2.158 Zeichen (EnWG); der längste § hat 32.331
Zeichen (EnWG). Eine Teilung unterhalb der §-Ebene ist also unvermeidlich.

## Entscheidung
Zwei Strategien, beide als `CHUNKING_VERSION` versioniert und in `index_configs` gespeichert:

- **paragraph** (Standard): ein Chunk pro §. Ist der § länger als `chunk_max_chars` (2.000),
  werden aufeinanderfolgende Absätze bis zu dieser Grenze zusammengefasst.
- **absatz**: ein Chunk pro Absatz.

Ein Absatz, der immer noch zu lang ist, wird an Aufzählungszeilen geteilt, dann an Satzenden und
nur als letzter Ausweg an Wortgrenzen. Jeder Chunk wird mit einem kurzen Kontext-Header eingebettet:
`<Gesetz> <§> Abs. <n> <Überschrift>` plus die innerste Abschnittsüberschrift.

2.000 Zeichen ≈ 500 Tokens bei deutschem Gesetzestext; das passt in das 512-Token-Fenster des
Embedding-Modells (ADR 0002).

## Konsequenzen
- Jeder Chunk gehört zu genau einem §, die Quellenangabe ist also immer eindeutig.
- Die beiden Strategien werden in der Evaluation verglichen (`docs/evaluation.md`).
- Eine Änderung der Chunking-Logik erfordert eine neue `CHUNKING_VERSION`; der nächste Ingest legt
  eine neue Index-Konfiguration an und chunkt jede Norm neu (alte Chunks bleiben, bis man sie
  löscht).
