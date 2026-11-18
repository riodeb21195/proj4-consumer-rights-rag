"""Build the small, committed law set used by tests and the CI quality gate.

Usage: uv run python scripts/build_fixtures.py data/raw tests/fixtures/laws

Takes downloaded XML (data/raw/<slug>/*.xml) and copies EVO and PAngV unchanged; the BGB is cut
down to core consumer provisions so the fixture stays small. Text is not modified.
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

from rag.ingest.parse_xml import paragraph_sort_key

BGB_KEEP = [("13", "14"), ("312", "312k"), ("355", "357d"), ("433", "479"), ("651a", "651y")]


def _keep(enbez: str) -> bool:
    key = paragraph_sort_key(enbez)
    if key is None:
        return False
    for lo, hi in BGB_KEEP:
        lo_key, hi_key = paragraph_sort_key(lo), paragraph_sort_key(hi)
        assert lo_key is not None and hi_key is not None
        if lo_key <= key <= hi_key:
            return True
    return False


def trim_bgb(xml: bytes) -> bytes:
    root = etree.fromstring(xml, etree.XMLParser(load_dtd=False, no_network=True))
    norms = root.findall("norm")
    for norm in norms[1:]:
        meta = norm.find("metadaten")
        if meta is None or meta.find("gliederungseinheit") is not None:
            continue  # keep section headings so section paths stay realistic
        if not _keep((meta.findtext("enbez") or "").strip()):
            root.remove(norm)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


def main(raw_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for slug in ("evo_2023", "pangv_2022", "bgb"):
        xml = next((raw_dir / slug).glob("*.xml")).read_bytes()
        if slug == "bgb":
            xml = trim_bgb(xml)
        (out_dir / f"{slug}.xml").write_bytes(xml)
        print(f"{slug}: {len(xml) // 1024} KiB")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
