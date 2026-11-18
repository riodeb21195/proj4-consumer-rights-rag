import io
import zipfile

import httpx
import pytest

from rag.ingest.download import (
    DownloadError,
    HttpLawSource,
    LocalLawSource,
    extract_xml,
    make_source,
)


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _source(handler) -> HttpLawSource:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpLawSource("https://example.test/", client=client, retries=2, backoff_s=0)


def test_extract_xml_ignores_images():
    assert extract_xml(_zip({"a.xml": b"<x/>", "img.jpg": b"\xff"})) == b"<x/>"


@pytest.mark.parametrize(
    "payload", [b"not a zip", _zip({"a.jpg": b""}), _zip({"a.xml": b"", "b.xml": b""})]
)
def test_extract_xml_rejects_bad_archives(payload):
    with pytest.raises(DownloadError):
        extract_xml(payload)


def test_fetch_ok_returns_validators():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/bgb/xml.zip"
        return httpx.Response(200, content=_zip({"b.xml": b"<d/>"}), headers={"ETag": '"e1"'})

    result = _source(handler).fetch("bgb")
    assert result.xml == b"<d/>"
    assert result.etag == '"e1"'
    assert not result.not_modified
    assert len(result.sha256) == 64


def test_fetch_conditional_not_modified():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["If-None-Match"] == '"e1"'
        assert request.headers["If-Modified-Since"] == "lm"
        return httpx.Response(304)

    result = _source(handler).fetch("bgb", etag='"e1"', last_modified="lm")
    assert result.not_modified
    with pytest.raises(ValueError):
        _ = result.sha256


def test_fetch_retries_server_errors_then_fails():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(DownloadError):
        _source(handler).fetch("bgb")
    assert len(calls) == 2


def test_fetch_retries_transport_errors_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(200, content=_zip({"b.xml": b"<d/>"}))

    assert _source(handler).fetch("bgb").xml == b"<d/>"


def test_fetch_404_fails_fast():
    with pytest.raises(DownloadError):
        _source(lambda r: httpx.Response(404)).fetch("nope")


def test_local_source(tmp_path):
    (tmp_path / "pangv.xml").write_bytes(b"<d/>")
    src = LocalLawSource(tmp_path)
    assert src.fetch("pangv").xml == b"<d/>"
    with pytest.raises(DownloadError):
        src.fetch("missing")


def test_local_source_relative_path(tmp_path, monkeypatch):
    (tmp_path / "laws").mkdir()
    (tmp_path / "laws" / "evo.xml").write_bytes(b"<d/>")
    monkeypatch.chdir(tmp_path)
    result = make_source("laws").fetch("evo")
    assert result.source_url.startswith("file:///")


def test_make_source(tmp_path):
    assert isinstance(make_source(f"file://{tmp_path}"), LocalLawSource)
    assert isinstance(make_source(str(tmp_path)), LocalLawSource)
    assert isinstance(
        make_source("https://www.gesetze-im-internet.de", user_agent="x"), HttpLawSource
    )
