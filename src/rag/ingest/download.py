"""Fetch law XML from gesetze-im-internet.de (or a local directory for tests and demos).

Downloads are conditional (ETag / Last-Modified), so an unchanged law costs one 304 response.
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from rag.ingest.hashing import sha256_bytes

log = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchResult:
    slug: str
    source_url: str
    xml: bytes | None  # None means "not modified since the given validators"
    etag: str | None = None
    last_modified: str | None = None

    @property
    def not_modified(self) -> bool:
        return self.xml is None

    @property
    def sha256(self) -> str:
        if self.xml is None:
            raise ValueError("no content for a not-modified result")
        return sha256_bytes(self.xml)


class LawSource(Protocol):
    def fetch(
        self, slug: str, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult: ...


def extract_xml(zip_bytes: bytes) -> bytes:
    """Return the law XML inside the download archive (it also contains images)."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if len(xml_names) != 1:
                raise DownloadError(f"expected exactly one XML file in archive, got {xml_names}")
            return zf.read(xml_names[0])
    except zipfile.BadZipFile as exc:
        raise DownloadError(f"not a zip archive: {exc}") from exc


class HttpLawSource:
    def __init__(
        self,
        base_url: str,
        client: httpx.Client | None = None,
        retries: int = 3,
        backoff_s: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=60.0, follow_redirects=True)
        self.retries = retries
        self.backoff_s = backoff_s

    def url_for(self, slug: str) -> str:
        return f"{self.base_url}/{slug}/xml.zip"

    def _get(self, url: str, headers: dict[str, str]) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.client.get(url, headers=headers)
                if resp.status_code < 500:
                    return resp
                last_exc = DownloadError(f"{url}: HTTP {resp.status_code}")
            except httpx.TransportError as exc:
                last_exc = exc
            log.warning("download attempt failed", extra={"url": url, "attempt": attempt})
            if attempt < self.retries:
                time.sleep(self.backoff_s * attempt)
        raise DownloadError(f"{url}: giving up after {self.retries} attempts") from last_exc

    def fetch(
        self, slug: str, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult:
        url = self.url_for(slug)
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        resp = self._get(url, headers)
        if resp.status_code == 304:
            return FetchResult(slug, url, None, etag, last_modified)
        if resp.status_code != 200:
            raise DownloadError(f"{url}: HTTP {resp.status_code}")
        return FetchResult(
            slug=slug,
            source_url=url,
            xml=extract_xml(resp.content),
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )


class LocalLawSource:
    """Reads ``<directory>/<slug>.xml``. Used by tests, CI and the failure-scenario scripts."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def fetch(
        self, slug: str, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult:
        path = self.directory / f"{slug}.xml"
        if not path.is_file():
            raise DownloadError(f"{path} not found")
        return FetchResult(slug=slug, source_url=path.as_uri(), xml=path.read_bytes())


def make_source(base_url: str, timeout_s: float = 60.0, user_agent: str = "") -> LawSource:
    """``file://`` URLs and plain paths map to a local source, everything else to HTTP."""
    if base_url.startswith("file://"):
        return LocalLawSource(Path(base_url.removeprefix("file://")))
    if not base_url.startswith(("http://", "https://")):
        return LocalLawSource(Path(base_url))
    headers = {"User-Agent": user_agent} if user_agent else {}
    client = httpx.Client(timeout=timeout_s, follow_redirects=True, headers=headers)
    return HttpLawSource(base_url, client=client)
