"""Structure-aware chunking of legal provisions.

Strategies (see docs/decisions/0001-chunking.md):
- ``paragraph``: one chunk per § if it fits; longer §§ are cut at Absatz boundaries.
- ``absatz``: one chunk per Absatz.

In both cases an Absatz that is still too long is split at enumeration items, then sentences.
Every chunk carries a context header (law, §, heading) so it can be understood on its own.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from rag.ingest.hashing import content_hash

# Bump when chunk boundaries or embed text change: it forces a re-index via a new index config.
CHUNKING_VERSION = "v1"

_ABSATZ_RE = re.compile(r"^\((\d+[a-z]?)\)")
_SENTENCE_SPLIT = re.compile(r"(?<=[.;:])\s+(?=[A-ZÄÖÜ0-9(§])")


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    paragraph: str
    absatz: str | None
    heading: str
    text: str
    embed_text: str

    @property
    def content_hash(self) -> str:
        return content_hash(self.embed_text)


@dataclass(frozen=True)
class NormInput:
    """The parts of a norm the chunker needs (works for parsed and stored norms)."""

    law_abbreviation: str
    norm_key: str
    title: str
    section: str
    absaetze: Sequence[str]


def _absatz_label(text: str) -> str | None:
    m = _ABSATZ_RE.match(text)
    return m.group(1) if m else None


def _pack(pieces: Sequence[str], max_chars: int, sep: str) -> list[str]:
    """Greedily join pieces in order without exceeding max_chars (a single piece may exceed it)."""
    out: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}{sep}{piece}" if current else piece
        if current and len(candidate) > max_chars:
            out.append(current)
            current = piece
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def split_long(text: str, max_chars: int) -> list[str]:
    """Split one Absatz: first at enumeration lines, then at sentence ends, then at words."""
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    for block in _pack(text.split("\n"), max_chars, "\n"):
        if len(block) <= max_chars:
            parts.append(block)
            continue
        for sentence_block in _pack(_SENTENCE_SPLIT.split(block), max_chars, " "):
            if len(sentence_block) <= max_chars:
                parts.append(sentence_block)
            else:  # a single huge sentence (rare): fall back to word boundaries
                parts.extend(_pack(sentence_block.split(" "), max_chars, " "))
    return parts


def _label(labels: Sequence[str | None]) -> str | None:
    present = [x for x in labels if x]
    if not present:
        return None
    return present[0] if present[0] == present[-1] else f"{present[0]}-{present[-1]}"


def _segments(norm: NormInput, strategy: str, max_chars: int) -> list[tuple[str, str | None]]:
    """(text, absatz label) pairs according to the strategy."""
    units: list[tuple[str, str | None]] = []
    current_label: str | None = None
    for absatz in norm.absaetze:
        current_label = _absatz_label(absatz) or current_label
        for piece in split_long(absatz, max_chars):
            units.append((piece, current_label))
    if strategy == "absatz":
        return units
    if strategy != "paragraph":
        raise ValueError(f"unknown chunking strategy: {strategy}")
    merged: list[tuple[str, list[str | None]]] = []
    for text, label in units:
        if merged and len(merged[-1][0]) + 1 + len(text) <= max_chars:
            merged[-1] = (f"{merged[-1][0]}\n{text}", [*merged[-1][1], label])
        else:
            merged.append((text, [label]))
    return [(text, _label(labels)) for text, labels in merged]


def chunk_norm(norm: NormInput, strategy: str, max_chars: int) -> list[Chunk]:
    heading = f"{norm.law_abbreviation} {norm.norm_key} {norm.title}".strip()
    context = norm.section.rsplit(" > ", 1)[-1] if norm.section else ""
    chunks: list[Chunk] = []
    for i, (text, absatz) in enumerate(_segments(norm, strategy, max_chars)):
        absatz_ref = f" Abs. {absatz}" if absatz else ""
        header = f"{norm.law_abbreviation} {norm.norm_key}{absatz_ref} {norm.title}".strip()
        embed_text = "\n".join(p for p in (header, context, text) if p)
        chunks.append(
            Chunk(
                chunk_index=i,
                paragraph=norm.norm_key,
                absatz=absatz,
                heading=heading,
                text=text,
                embed_text=embed_text,
            )
        )
    return chunks
