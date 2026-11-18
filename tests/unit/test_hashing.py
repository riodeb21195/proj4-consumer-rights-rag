from rag.ingest.hashing import content_hash, normalize_text, sha256_bytes


def test_sha256_known_value():
    assert sha256_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_whitespace_changes_do_not_change_hash():
    assert content_hash("§ 1", "Text  mit\nUmbruch") == content_hash("§ 1", "Text mit Umbruch")


def test_field_boundaries_matter():
    assert content_hash("ab", "c") != content_hash("a", "bc")


def test_normalize_text():
    assert normalize_text("  a \t b\n") == "a b"
