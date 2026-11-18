# 0000 – Architekturentscheidungen festhalten

- Status: angenommen
- Datum: 18.11.2026

## Kontext
Mehrere Entscheidungen in diesem Projekt (Chunking, Embedding-Modell, Vektorspeicher,
Retrieval-Strategie) haben Zielkonflikte, die man am Code allein nicht erkennt.

## Entscheidung
Jede wichtige Entscheidung wird als kurzer ADR in `docs/decisions/NNNN-titel.md` festgehalten, mit
den Abschnitten *Kontext*, *Entscheidung*, *Konsequenzen* und, wo sinnvoll, *Geprüfte
Alternativen*.

## Konsequenzen
Entscheidungen lassen sich in Pull Requests prüfen und liegen neben dem Code, den sie erklären.
Überholte ADRs werden nicht gelöscht, sondern als überholt markiert.
