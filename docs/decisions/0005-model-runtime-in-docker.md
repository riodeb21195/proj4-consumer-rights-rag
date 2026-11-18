# 0005 – Modell-Laufzeit nur in Linux-Containern

- Status: angenommen
- Datum: 18.11.2026

## Kontext
PyTorch veröffentlicht seit Version 2.2.2 keine Wheels mehr für macOS x86_64. Geprüft auf dem
Entwicklungsrechner (Intel-MacBook von 2019) am 18.11.2026:

- `uv add sentence-transformers` schlägt fehl: Torch 2.15.0 hat Wheels nur für
  manylinux x86_64/aarch64, macOS arm64 und Windows,
- mit festgesetztem Torch 2.2.2 klappt die Installation, aber transformers 5.23 stürzt beim Import
  ab (`NameError: name 'nn' is not defined`).

## Entscheidung
- Die Modell-Abhängigkeiten liegen im optionalen Extra `ml` (sentence-transformers, Torch nur für
  CPU aus dem PyTorch-CPU-Index unter Linux).
- API, Ingest/Airflow und Evaluation laufen in Linux-Containern, die `ml` installieren.
- Das lokale venv ist für Linting und Tests; Tests nutzen `FakeEmbedder`. Der eine Test, der das
  echte Modell lädt, wird übersprungen, wenn sentence-transformers fehlt, und läuft in der CI.

## Konsequenzen
- Dasselbe Image läuft lokal, in der CI und würde so auch in Produktion laufen.
- Lokale Experimente mit dem echten Modell gehen über `docker compose run` statt über das venv auf
  dem Rechner.
