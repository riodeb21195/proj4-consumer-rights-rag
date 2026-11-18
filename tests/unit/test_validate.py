from rag.process.chunk import Chunk
from rag.process.validate import ValidationReport, validate_chunks


def _chunk(text: str, idx: int = 0, para: str = "§ 1") -> Chunk:
    return Chunk(idx, para, None, "H", text, f"H\n{text}")


def test_detects_empty_duplicate_and_too_long():
    report = ValidationReport()
    seen: set[str] = set()
    chunks = [
        _chunk("   ", 0),
        _chunk("gültiger Text", 1),
        _chunk("gültiger Text", 2),
        _chunk("x" * 50, 3),
    ]
    valid = validate_chunks(chunks, min_chars=5, max_chars=20, seen_hashes=seen, report=report)
    assert [c.chunk_index for c in valid] == [1, 3]
    assert report.counts() == {"empty": 1, "duplicate": 1, "too_long": 1}


def test_duplicates_across_calls_share_seen_hashes():
    report = ValidationReport()
    seen: set[str] = set()
    validate_chunks(
        [_chunk("Text eins")], min_chars=1, max_chars=99, seen_hashes=seen, report=report
    )
    again = validate_chunks(
        [_chunk("Text eins")], min_chars=1, max_chars=99, seen_hashes=seen, report=report
    )
    assert again == []
