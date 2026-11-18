"""Shared helpers for the failure-scenario demos (run inside the api container, see Makefile).

Each scenario ingests a private copy of the PAngV under the slug ``demo_pangv`` with the real
embedding model, database and MinIO, manipulates the XML like an upstream change would, ingests
again and prints what happened. The demo law is removed afterwards; ingest_runs stay as audit log.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lxml import etree

from rag.config import LawSelection, get_settings
from rag.ingest.download import LocalLawSource
from rag.ingest.pipeline import IngestPipeline, RunSummary, build_pipeline
from rag.logging import configure_logging

SLUG = "demo_pangv"
FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "laws" / "pangv_2022.xml"


@contextmanager
def demo_pipeline() -> Iterator[tuple[IngestPipeline, Path]]:
    settings = get_settings()
    configure_logging("WARNING")
    workdir = Path(tempfile.mkdtemp(prefix="scenario-"))
    shutil.copy(FIXTURE, workdir / f"{SLUG}.xml")
    pipeline = build_pipeline(settings)
    pipeline.source = LocalLawSource(workdir)
    try:
        yield pipeline, workdir / f"{SLUG}.xml"
    finally:
        # chunks/norms reference law_versions without cascade, so delete bottom-up.
        with pipeline.store.transaction():
            for table in ("chunks", "norms", "laws"):
                key = "slug" if table == "laws" else "law_slug"
                pipeline.store.conn.execute(
                    f"DELETE FROM {table} WHERE {key} = %s",  # noqa: S608 - fixed identifiers
                    (SLUG,),
                )
        pipeline.store.close()
        shutil.rmtree(workdir)


def ingest(pipeline: IngestPipeline) -> RunSummary:
    # activate=False: the demo must never switch the index the API is serving.
    return pipeline.run([LawSelection(slug=SLUG)], trigger="scenario", activate=False)


def chunks(pipeline: IngestPipeline) -> dict[int, tuple[str, str]]:
    """chunk id -> (paragraph, content hash) of the demo law."""
    rows = pipeline.store.conn.execute(
        "SELECT id, paragraph, content_hash FROM chunks WHERE law_slug = %s", (SLUG,)
    ).fetchall()
    return {r["id"]: (r["paragraph"], r["content_hash"]) for r in rows}


def report(title: str, summary: RunSummary) -> None:
    law = summary.laws[0]
    print(f"\n== {title}")
    print(
        f"   run {summary.run_id}: status={summary.status} law={law.status} "
        f"added={law.norms_added} changed={law.norms_changed} removed={law.norms_removed} "
        f"unchanged={law.norms_unchanged} chunks_written={law.chunks_written}"
    )
    if law.error:
        print(f"   error: {law.error}")


def _tree(path: Path) -> etree._ElementTree:
    return etree.parse(str(path), etree.XMLParser(load_dtd=False, no_network=True))


def _norm(tree: etree._ElementTree, enbez: str) -> etree._Element:
    for norm in tree.getroot().iter("norm"):
        if (norm.findtext("metadaten/enbez") or "").strip() == enbez:
            return norm
    raise KeyError(enbez)


def amend(path: Path, enbez: str, old: str, new: str) -> None:
    tree = _tree(path)
    for p in _norm(tree, enbez).iter("P"):
        if p.text and old in p.text:
            p.text = p.text.replace(old, new)
            tree.getroot().set("builddate", "20991231235959")
            tree.write(str(path), xml_declaration=True, encoding="UTF-8")
            return
    raise ValueError(f"{old!r} not in {enbez}")


def repeal(path: Path, enbez: str) -> None:
    tree = _tree(path)
    norm = _norm(tree, enbez)
    title = norm.find("metadaten/titel")
    if title is not None:
        title.text = "(weggefallen)"
    content = norm.find("textdaten/text/Content")
    if content is not None:
        for child in list(content):
            content.remove(child)
    tree.write(str(path), xml_declaration=True, encoding="UTF-8")


def check(condition: bool, message: str) -> None:
    print(f"   [{'OK' if condition else 'FAIL'}] {message}")
    if not condition:
        sys.exit(1)
