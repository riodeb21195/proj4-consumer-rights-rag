"""Incremental ingest: fetch -> archive -> parse -> diff -> chunk -> validate -> embed -> index.

Change detection happens on three levels:
1. HTTP validators (ETag / Last-Modified): unchanged downloads are skipped entirely.
2. XML SHA-256: a re-served but identical file does not touch the index.
3. Per-norm content hash: only new or changed provisions are re-chunked and re-embedded;
   provisions that disappeared (or were repealed) are deleted together with their chunks.

Each law is processed in its own transaction, so a broken law is rolled back and reported
while the others continue. Re-running is idempotent.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rag.config import LawSelection, Settings, get_settings
from rag.ingest.download import LawSource, make_source
from rag.ingest.parse_xml import Law, Norm, in_ranges, norm_url, parse_law
from rag.logging import configure_logging
from rag.process.chunk import CHUNKING_VERSION, NormInput, chunk_norm
from rag.process.embed import Embedder, make_embedder
from rag.process.validate import ValidationReport, validate_chunks
from rag.store.object_store import RawStore, raw_key
from rag.store.vector_store import ChunkRecord, IndexConfig, VectorStore

log = logging.getLogger(__name__)


@dataclass
class LawResult:
    slug: str
    status: str = "pending"  # new | updated | unchanged | not_modified | failed
    norms_added: int = 0
    norms_changed: int = 0
    norms_removed: int = 0
    norms_unchanged: int = 0
    chunks_written: int = 0
    validation: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    seconds: float = 0.0


@dataclass
class RunSummary:
    run_id: int
    status: str
    index_config_id: int
    laws: list[LawResult]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IngestPipeline:
    def __init__(
        self,
        settings: Settings,
        store: VectorStore,
        raw_store: RawStore,
        source: LawSource,
        embedder: Embedder,
    ) -> None:
        self.settings = settings
        self.store = store
        self.raw_store = raw_store
        self.source = source
        self.embedder = embedder

    def index_config(self) -> IndexConfig:
        return self.store.ensure_index_config(
            self.settings.chunking_strategy,
            CHUNKING_VERSION,
            self.embedder.model_name,
            self.embedder.dim,
        )

    def run(
        self,
        laws: list[LawSelection] | None = None,
        trigger: str = "manual",
        activate: bool = True,
    ) -> RunSummary:
        laws = laws if laws is not None else self.settings.laws
        config = self.index_config()
        run_id = self.store.start_run(trigger, config.id)
        log.info("ingest run started", extra={"run_id": run_id, "index_config_id": config.id})
        self.raw_store.ensure_bucket()

        results = [self.ingest_law(run_id, config, selection) for selection in laws]

        failed = [r for r in results if r.status == "failed"]
        if not failed:
            status = "success"
        elif len(failed) < len(results):
            status = "partial"
        else:
            status = "failed"
        if activate and status != "failed":
            self.store.activate_config(config.id)
        stats = {
            "laws": {r.slug: asdict(r) for r in results},
            "index": dict(self.store.chunk_stats(config.id)),
        }
        errors = [{"law": r.slug, "error": r.error} for r in failed]
        self.store.finish_run(run_id, status, stats, errors)
        log.info("ingest run finished", extra={"run_id": run_id, "status": status})
        return RunSummary(run_id, status, config.id, results)

    def ingest_law(self, run_id: int, config: IndexConfig, selection: LawSelection) -> LawResult:
        result = LawResult(slug=selection.slug)
        started = time.monotonic()
        try:
            self._ingest_law(run_id, config, selection, result)
        except Exception as exc:  # one broken law must not stop the others
            result.status = "failed"
            result.error = f"{type(exc).__name__}: {exc}"
            log.exception("law ingest failed", extra={"law": selection.slug, "run_id": run_id})
        result.seconds = round(time.monotonic() - started, 2)
        log.info("law processed", extra={"run_id": run_id, **asdict(result)})
        return result

    def _ingest_law(
        self, run_id: int, config: IndexConfig, selection: LawSelection, result: LawResult
    ) -> None:
        slug = selection.slug
        current = self.store.current_version(slug)
        fetched = self.source.fetch(
            slug,
            etag=current.etag if current else None,
            last_modified=current.last_modified if current else None,
        )
        if current and (fetched.not_modified or fetched.sha256 == current.xml_sha256):
            # Source unchanged. Still index norms that lack chunks for this config (re-index).
            result.status = "not_modified" if fetched.not_modified else "unchanged"
            with self.store.transaction():
                if not fetched.not_modified:
                    self.store.update_validators(current.id, fetched.etag, fetched.last_modified)
                result.norms_unchanged = len(self.store.norm_hashes(slug))
                abbreviation = self.store.law_abbreviation(slug)
                result.chunks_written = self._index_pending(
                    config, slug, abbreviation, current.stand, result
                )
            return

        assert fetched.xml is not None
        law = parse_law(fetched.xml, slug)  # raises XmlParseError for broken files
        key = raw_key(slug, law.builddate.strftime("%Y%m%d%H%M%S"), fetched.sha256)
        self.raw_store.put_if_absent(
            key, fetched.xml, {"law": slug, "sha256": fetched.sha256, "source": fetched.source_url}
        )

        with self.store.transaction():
            self.store.upsert_law(slug, law.abbreviation, law.title)
            version_id = self.store.record_version(
                slug,
                builddate=law.builddate,
                stand=law.stand,
                xml_sha256=fetched.sha256,
                raw_object_key=key,
                source_url=fetched.source_url,
                etag=fetched.etag,
                last_modified=fetched.last_modified,
                run_id=run_id,
            )
            self._sync_norms(law, selection, version_id, result)
            result.status = "updated" if current else "new"
            result.chunks_written = self._index_pending(
                config, slug, law.abbreviation, law.stand, result
            )

    def _selected_norms(self, law: Law, selection: LawSelection) -> dict[str, Norm]:
        norms: dict[str, Norm] = {}
        for norm in law.norms:
            if norm.repealed or not in_ranges(norm, selection.ranges):
                continue
            if norm.enbez in norms:
                log.warning("duplicate norm key", extra={"law": law.slug, "norm": norm.enbez})
                continue
            norms[norm.enbez] = norm
        return norms

    def _sync_norms(
        self, law: Law, selection: LawSelection, version_id: int, result: LawResult
    ) -> None:
        existing = self.store.norm_hashes(law.slug)
        wanted = self._selected_norms(law, selection)
        removed = sorted(set(existing) - set(wanted))
        result.norms_removed = self.store.delete_norms(law.slug, removed)
        if removed:
            log.info("norms removed", extra={"law": law.slug, "norms": removed})
        # Unchanged norms (and their chunks) move to the new version without being rewritten.
        self.store.touch_norms_version(law.slug, version_id)
        for key, norm in wanted.items():
            old = existing.get(key)
            if old and old[1] == norm.content_hash:
                result.norms_unchanged += 1
                continue
            if old:
                result.norms_changed += 1
            else:
                result.norms_added += 1
            self.store.upsert_norm(
                law.slug,
                norm_key=key,
                doknr=norm.doknr,
                title=norm.title,
                section=norm.section,
                absaetze=norm.absaetze,
                content_hash=norm.content_hash,
                law_version_id=version_id,
                source_url=norm_url(self.settings.law_base_url, law.slug, key),
            )

    def _index_pending(
        self, config: IndexConfig, slug: str, abbreviation: str, stand: str, result: LawResult
    ) -> int:
        pending = self.store.norms_needing_chunks(config.id, slug)
        if not pending:
            return 0
        report = ValidationReport()
        seen: set[str] = set()
        planned = []
        for norm in pending:
            chunks = chunk_norm(
                NormInput(abbreviation, norm.norm_key, norm.title, norm.section, norm.absaetze),
                config.chunking_strategy,
                self.settings.chunk_max_chars,
            )
            valid = validate_chunks(
                chunks,
                min_chars=self.settings.chunk_min_chars,
                max_chars=self.settings.chunk_max_chars,
                seen_hashes=seen,
                report=report,
            )
            planned.append((norm, valid))

        texts = [c.embed_text for _, chunks in planned for c in chunks]
        vectors = self.embedder.embed_passages(texts)
        written = 0
        offset = 0
        for norm, chunks in planned:
            records = [
                ChunkRecord(
                    chunk_index=c.chunk_index,
                    paragraph=c.paragraph,
                    absatz=c.absatz,
                    heading=c.heading,
                    text=c.text,
                    embed_text=c.embed_text,
                    content_hash=c.content_hash,
                    embedding=vectors[offset + i],
                )
                for i, c in enumerate(chunks)
            ]
            offset += len(chunks)
            written += self.store.replace_chunks(
                config,
                norm,
                law_slug=slug,
                law_abbreviation=abbreviation,
                stand=stand,
                chunks=records,
            )
        result.validation = report.counts()
        if report.issues:
            log.warning("chunk validation issues", extra={"law": slug, **report.counts()})
        return written


def build_pipeline(settings: Settings, source_url: str | None = None) -> IngestPipeline:
    store = VectorStore.connect(settings.database_url)
    raw_store = RawStore.from_settings(
        settings.s3_endpoint_url,
        settings.s3_access_key,
        settings.s3_secret_key.get_secret_value(),
        settings.s3_bucket,
    )
    source = make_source(
        source_url or settings.law_base_url, settings.http_timeout_s, settings.user_agent
    )
    embedder = make_embedder(settings.embedding_model, settings.embedding_batch_size)
    return IngestPipeline(settings, store, raw_store, source, embedder)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Incrementally ingest German laws.")
    parser.add_argument("--laws", help="comma-separated slugs (default: all configured)")
    parser.add_argument("--source", help="base URL or local directory (default: settings)")
    parser.add_argument("--trigger", default="manual")
    parser.add_argument("--schema", type=Path, help="apply this SQL schema file first")
    parser.add_argument("--no-activate", action="store_true", help="do not switch active index")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    laws = settings.laws
    if args.laws:
        wanted = args.laws.split(",")
        by_slug = {law.slug: law for law in settings.laws}
        laws = [by_slug.get(slug, LawSelection(slug=slug)) for slug in wanted]

    pipeline = build_pipeline(settings, args.source)
    if args.schema:
        pipeline.store.apply_schema(args.schema)
    summary = pipeline.run(laws, trigger=args.trigger, activate=not args.no_activate)
    pipeline.store.close()
    return 0 if summary.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
