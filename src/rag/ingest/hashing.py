"""Content hashing used for change detection."""

from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_text(text: str) -> str:
    """Collapse whitespace so formatting-only changes in the source do not trigger reprocessing."""
    return _WS.sub(" ", text).strip()


def content_hash(*parts: str) -> str:
    """Stable hash over several text fields (separator prevents ``("ab", "c") == ("a", "bc")``)."""
    joined = "\x1f".join(normalize_text(p) for p in parts)
    return sha256_bytes(joined.encode("utf-8"))
