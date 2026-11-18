"""Chunk validation: detect empty, too long and duplicate chunks before they reach the index."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from rag.process.chunk import Chunk


@dataclass(frozen=True)
class Issue:
    kind: str  # "empty" | "too_long" | "duplicate"
    paragraph: str
    chunk_index: int
    detail: str = ""


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for issue in self.issues:
            out[issue.kind] = out.get(issue.kind, 0) + 1
        return out


def validate_chunks(
    chunks: Sequence[Chunk],
    *,
    min_chars: int,
    max_chars: int,
    seen_hashes: set[str],
    report: ValidationReport,
) -> list[Chunk]:
    """Return the chunks that may be indexed.

    - empty / near-empty chunks are dropped,
    - duplicates (same embed text already seen in this run) are dropped,
    - too long chunks are kept but reported: the embedding model truncates them, so retrieval
      quality for their tail may suffer. ``seen_hashes`` is updated in place.
    """
    valid: list[Chunk] = []
    for chunk in chunks:
        if len(chunk.text.strip()) < min_chars:
            report.issues.append(Issue("empty", chunk.paragraph, chunk.chunk_index))
            continue
        h = chunk.content_hash
        if h in seen_hashes:
            report.issues.append(Issue("duplicate", chunk.paragraph, chunk.chunk_index))
            continue
        if len(chunk.text) > max_chars:
            report.issues.append(
                Issue("too_long", chunk.paragraph, chunk.chunk_index, f"{len(chunk.text)} chars")
            )
        seen_hashes.add(h)
        valid.append(chunk)
    return valid
