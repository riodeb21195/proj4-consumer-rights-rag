"""Discover available laws from the official table of contents (``gii-toc.xml``)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from lxml import etree

from rag.config import LawSelection, get_settings
from rag.logging import configure_logging

log = logging.getLogger(__name__)

TOC_PATH = "/gii-toc.xml"


@dataclass(frozen=True)
class TocEntry:
    slug: str
    title: str
    url: str


def parse_toc(xml: bytes) -> dict[str, TocEntry]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    root = etree.fromstring(xml, parser=parser)
    entries: dict[str, TocEntry] = {}
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        # link looks like http://www.gesetze-im-internet.de/<slug>/xml.zip
        parts = [p for p in urlparse(link).path.split("/") if p]
        if len(parts) >= 2 and parts[-1] == "xml.zip":
            entries[parts[-2]] = TocEntry(slug=parts[-2], title=title, url=link)
    return entries


def fetch_toc(base_url: str, client: httpx.Client | None = None) -> dict[str, TocEntry]:
    client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    resp = client.get(base_url.rstrip("/") + TOC_PATH)
    resp.raise_for_status()
    return parse_toc(resp.content)


def check_selection(selection: list[LawSelection], toc: dict[str, TocEntry]) -> list[str]:
    """Return configured slugs that are not (or no longer) published."""
    missing = [law.slug for law in selection if law.slug not in toc]
    for slug in missing:
        log.error("configured law not found in table of contents", extra={"law": slug})
    return missing


def main() -> int:
    """Exit non-zero if a configured law is no longer published (first task of the DAG)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    client = httpx.Client(
        timeout=settings.http_timeout_s,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent},
    )
    toc = fetch_toc(settings.law_base_url, client)
    missing = check_selection(settings.laws, toc)
    log.info(
        "sources checked",
        extra={"published": len(toc), "configured": len(settings.laws), "missing": missing},
    )
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
