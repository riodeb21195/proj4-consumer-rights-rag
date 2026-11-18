import pytest

from rag.store.object_store import RawStore, raw_key

pytestmark = pytest.mark.integration


def test_put_is_idempotent(raw_store: RawStore):
    key = raw_key("pangv_2022", "20261102215513", "ab" * 32)
    assert key == "pangv_2022/20261102215513_abababababababab.xml"
    assert raw_store.put_if_absent(key, b"<d/>", {"law": "pangv_2022"})
    assert not raw_store.put_if_absent(key, b"<d/>", {"law": "pangv_2022"})
    assert raw_store.get(key) == b"<d/>"


def test_ensure_bucket_twice(raw_store: RawStore):
    raw_store.ensure_bucket()
    assert not raw_store.exists("missing.xml")
