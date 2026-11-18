"""Postgres + pgvector access: laws, versions, norms, chunks, runs and search queries."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

Row = dict[str, Any]


@dataclass(frozen=True)
class IndexConfig:
    id: int
    chunking_strategy: str
    chunking_version: str
    embedding_model: str
    embedding_dim: int


@dataclass(frozen=True)
class LawVersion:
    id: int
    xml_sha256: str
    etag: str | None
    last_modified: str | None
    builddate: datetime
    stand: str


@dataclass(frozen=True)
class StoredNorm:
    id: int
    norm_key: str
    title: str
    section: str
    absaetze: list[str]
    content_hash: str
    source_url: str
    law_version_id: int


@dataclass(frozen=True)
class ChunkRecord:
    chunk_index: int
    paragraph: str
    absatz: str | None
    heading: str
    text: str
    embed_text: str
    content_hash: str
    embedding: np.ndarray[Any, np.dtype[np.float32]]


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    score: float
    law_slug: str
    law_abbreviation: str
    paragraph: str
    absatz: str | None
    heading: str
    text: str
    stand: str
    source_url: str
    law_version_id: int


_HIT_COLUMNS = """c.id AS chunk_id, c.law_slug, c.law_abbreviation, c.paragraph, c.absatz,
    c.heading, c.text, c.stand, c.source_url, c.law_version_id"""


def _hit(row: Row) -> SearchHit:
    return SearchHit(
        chunk_id=row["chunk_id"],
        score=float(row["score"]),
        law_slug=row["law_slug"],
        law_abbreviation=row["law_abbreviation"],
        paragraph=row["paragraph"],
        absatz=row["absatz"],
        heading=row["heading"],
        text=row["text"],
        stand=row["stand"],
        source_url=row["source_url"],
        law_version_id=row["law_version_id"],
    )


class VectorStore:
    def __init__(self, conn: psycopg.Connection[Row]) -> None:
        self.conn = conn

    @classmethod
    def connect(cls, dsn: str) -> VectorStore:
        # Autocommit: every multi-statement unit of work uses an explicit transaction() block.
        conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
        # The extension may not exist yet; apply_schema() creates and registers it then.
        with suppress(psycopg.ProgrammingError):
            register_vector(conn)
        return cls(conn)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.conn.transaction():
            yield

    def apply_schema(self, sql_file: Path) -> None:
        with self.conn.transaction():
            self.conn.execute(sql_file.read_text(encoding="utf-8").encode())
        register_vector(self.conn)

    # --- runs ---------------------------------------------------------------------------------

    def start_run(self, trigger: str, index_config_id: int | None) -> int:
        with self.conn.transaction():
            row = self.conn.execute(
                "INSERT INTO ingest_runs (trigger, index_config_id) VALUES (%s, %s) RETURNING id",
                (trigger, index_config_id),
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def finish_run(
        self, run_id: int, status: str, stats: dict[str, Any], errors: list[dict[str, Any]]
    ) -> None:
        with self.conn.transaction():
            self.conn.execute(
                """UPDATE ingest_runs SET finished_at = now(), status = %s, stats = %s, errors = %s
                   WHERE id = %s""",
                (status, json.dumps(stats), json.dumps(errors), run_id),
            )

    def get_run(self, run_id: int) -> Row | None:
        return self.conn.execute("SELECT * FROM ingest_runs WHERE id = %s", (run_id,)).fetchone()

    # --- index configs ------------------------------------------------------------------------

    def ensure_index_config(self, strategy: str, version: str, model: str, dim: int) -> IndexConfig:
        with self.conn.transaction():
            self.conn.execute(
                """INSERT INTO index_configs
                       (chunking_strategy, chunking_version, embedding_model, embedding_dim)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (strategy, version, model, dim),
            )
            row = self.conn.execute(
                """SELECT id FROM index_configs WHERE chunking_strategy = %s
                   AND chunking_version = %s AND embedding_model = %s""",
                (strategy, version, model),
            ).fetchone()
        assert row is not None
        return IndexConfig(row["id"], strategy, version, model, dim)

    def activate_config(self, config_id: int) -> None:
        with self.conn.transaction():
            self.conn.execute("UPDATE index_configs SET is_active = false WHERE is_active")
            self.conn.execute(
                "UPDATE index_configs SET is_active = true WHERE id = %s", (config_id,)
            )

    def active_config(self) -> IndexConfig | None:
        row = self.conn.execute("SELECT * FROM index_configs WHERE is_active").fetchone()
        return self._config(row) if row else None

    def get_config(self, config_id: int) -> IndexConfig | None:
        row = self.conn.execute(
            "SELECT * FROM index_configs WHERE id = %s", (config_id,)
        ).fetchone()
        return self._config(row) if row else None

    def list_configs(self) -> list[Row]:
        return self.conn.execute(
            """SELECT ic.*, count(c.id) AS chunk_count FROM index_configs ic
               LEFT JOIN chunks c ON c.index_config_id = ic.id GROUP BY ic.id ORDER BY ic.id"""
        ).fetchall()

    @staticmethod
    def _config(row: Row) -> IndexConfig:
        return IndexConfig(
            row["id"],
            row["chunking_strategy"],
            row["chunking_version"],
            row["embedding_model"],
            row["embedding_dim"],
        )

    # --- laws and versions --------------------------------------------------------------------

    def upsert_law(self, slug: str, abbreviation: str, title: str) -> None:
        self.conn.execute(
            """INSERT INTO laws (slug, abbreviation, title) VALUES (%s, %s, %s)
               ON CONFLICT (slug) DO UPDATE SET abbreviation = EXCLUDED.abbreviation,
                   title = EXCLUDED.title, updated_at = now()""",
            (slug, abbreviation, title),
        )

    def current_version(self, slug: str) -> LawVersion | None:
        row = self.conn.execute(
            "SELECT * FROM law_versions WHERE law_slug = %s AND is_current", (slug,)
        ).fetchone()
        if row is None:
            return None
        return LawVersion(
            row["id"],
            row["xml_sha256"],
            row["etag"],
            row["last_modified"],
            row["builddate"],
            row["stand"],
        )

    def record_version(
        self,
        slug: str,
        *,
        builddate: datetime,
        stand: str,
        xml_sha256: str,
        raw_object_key: str,
        source_url: str,
        etag: str | None,
        last_modified: str | None,
        run_id: int,
    ) -> int:
        """Insert (or reuse) a version row and make it the current one for the law."""
        self.conn.execute(
            "UPDATE law_versions SET is_current = false WHERE law_slug = %s AND is_current",
            (slug,),
        )
        row = self.conn.execute(
            """INSERT INTO law_versions (law_slug, builddate, stand, xml_sha256, raw_object_key,
                   source_url, etag, last_modified, ingest_run_id, is_current)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, true)
               ON CONFLICT (law_slug, xml_sha256) DO UPDATE SET is_current = true,
                   etag = EXCLUDED.etag, last_modified = EXCLUDED.last_modified
               RETURNING id""",
            (
                slug,
                builddate,
                stand,
                xml_sha256,
                raw_object_key,
                source_url,
                etag,
                last_modified,
                run_id,
            ),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def update_validators(
        self, version_id: int, etag: str | None, last_modified: str | None
    ) -> None:
        self.conn.execute(
            "UPDATE law_versions SET etag = %s, last_modified = %s WHERE id = %s",
            (etag, last_modified, version_id),
        )

    def law_versions(self, slug: str) -> list[Row]:
        return self.conn.execute(
            "SELECT * FROM law_versions WHERE law_slug = %s ORDER BY id", (slug,)
        ).fetchall()

    # --- norms --------------------------------------------------------------------------------

    def norm_hashes(self, slug: str) -> dict[str, tuple[int, str]]:
        rows = self.conn.execute(
            "SELECT id, norm_key, content_hash FROM norms WHERE law_slug = %s", (slug,)
        ).fetchall()
        return {r["norm_key"]: (r["id"], r["content_hash"]) for r in rows}

    def upsert_norm(
        self,
        slug: str,
        *,
        norm_key: str,
        doknr: str,
        title: str,
        section: str,
        absaetze: Sequence[str],
        content_hash: str,
        law_version_id: int,
        source_url: str,
    ) -> int:
        row = self.conn.execute(
            """INSERT INTO norms (law_slug, norm_key, doknr, title, section, absaetze,
                   content_hash, law_version_id, source_url)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (law_slug, norm_key) DO UPDATE SET doknr = EXCLUDED.doknr,
                   title = EXCLUDED.title, section = EXCLUDED.section,
                   absaetze = EXCLUDED.absaetze, content_hash = EXCLUDED.content_hash,
                   law_version_id = EXCLUDED.law_version_id, source_url = EXCLUDED.source_url,
                   updated_at = now()
               RETURNING id""",
            (
                slug,
                norm_key,
                doknr,
                title,
                section,
                json.dumps(list(absaetze)),
                content_hash,
                law_version_id,
                source_url,
            ),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def touch_norms_version(self, slug: str, law_version_id: int) -> None:
        """Unchanged norms now belong to the new law version too."""
        self.conn.execute(
            "UPDATE norms SET law_version_id = %s WHERE law_slug = %s", (law_version_id, slug)
        )
        self.conn.execute(
            "UPDATE chunks SET law_version_id = %s WHERE law_slug = %s", (law_version_id, slug)
        )

    def delete_norms(self, slug: str, norm_keys: Sequence[str]) -> int:
        if not norm_keys:
            return 0
        cur = self.conn.execute(
            "DELETE FROM norms WHERE law_slug = %s AND norm_key = ANY(%s)", (slug, list(norm_keys))
        )
        return cur.rowcount

    def norms_needing_chunks(self, config_id: int, slug: str) -> list[StoredNorm]:
        """Norms without up-to-date chunks for this config (new, changed, or config switched)."""
        rows = self.conn.execute(
            """SELECT n.* FROM norms n WHERE n.law_slug = %s AND NOT EXISTS (
                   SELECT 1 FROM chunks c WHERE c.norm_id = n.id AND c.index_config_id = %s
                     AND c.norm_content_hash = n.content_hash)
               ORDER BY n.id""",
            (slug, config_id),
        ).fetchall()
        return [
            StoredNorm(
                r["id"],
                r["norm_key"],
                r["title"],
                r["section"],
                list(r["absaetze"]),
                r["content_hash"],
                r["source_url"],
                r["law_version_id"],
            )
            for r in rows
        ]

    # --- chunks -------------------------------------------------------------------------------

    def replace_chunks(
        self,
        config: IndexConfig,
        norm: StoredNorm,
        *,
        law_slug: str,
        law_abbreviation: str,
        stand: str,
        chunks: Sequence[ChunkRecord],
    ) -> int:
        """Swap all chunks of one norm for one config. Returns the number of chunks written."""
        self.conn.execute(
            "DELETE FROM chunks WHERE index_config_id = %s AND norm_id = %s", (config.id, norm.id)
        )
        with self.conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO chunks (index_config_id, norm_id, chunk_index, law_slug,
                       law_abbreviation, paragraph, absatz, heading, text, embed_text,
                       content_hash, norm_content_hash, stand, source_url, law_version_id,
                       embedding)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (
                        config.id,
                        norm.id,
                        c.chunk_index,
                        law_slug,
                        law_abbreviation,
                        c.paragraph,
                        c.absatz,
                        c.heading,
                        c.text,
                        c.embed_text,
                        c.content_hash,
                        norm.content_hash,
                        stand,
                        norm.source_url,
                        norm.law_version_id,
                        c.embedding,
                    )
                    for c in chunks
                ],
            )
        return len(chunks)

    def chunk_stats(self, config_id: int) -> Row:
        row = self.conn.execute(
            """SELECT count(*) AS chunks, count(DISTINCT norm_id) AS norms,
                      count(DISTINCT law_slug) AS laws
               FROM chunks WHERE index_config_id = %s""",
            (config_id,),
        ).fetchone()
        assert row is not None
        return row

    def chunk_fingerprints(self, config_id: int) -> dict[int, tuple[str, datetime]]:
        """chunk id -> (content hash, created_at). Used to prove that untouched chunks survive."""
        rows = self.conn.execute(
            "SELECT id, content_hash, created_at FROM chunks WHERE index_config_id = %s",
            (config_id,),
        ).fetchall()
        return {r["id"]: (r["content_hash"], r["created_at"]) for r in rows}

    def get_chunks(self, chunk_ids: Sequence[int]) -> list[Row]:
        return self.conn.execute(
            """SELECT c.id, c.law_slug, c.paragraph, c.absatz, c.text, c.norm_id,
                      n.content_hash AS norm_hash, v.id AS law_version_id, v.builddate,
                      v.stand, v.xml_sha256, v.raw_object_key, v.source_url AS raw_source_url
               FROM chunks c JOIN norms n ON n.id = c.norm_id
               JOIN law_versions v ON v.id = c.law_version_id
               WHERE c.id = ANY(%s) ORDER BY c.id""",
            (list(chunk_ids),),
        ).fetchall()

    # --- search -------------------------------------------------------------------------------

    def vector_search(
        self, config_id: int, embedding: np.ndarray[Any, np.dtype[np.float32]], limit: int
    ) -> list[SearchHit]:
        with self.conn.transaction():
            # Iterative scans keep HNSW recall high when filtering by config (pgvector >= 0.8).
            self.conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            rows = self.conn.execute(
                f"""SELECT {_HIT_COLUMNS}, 1 - (c.embedding <=> %s) AS score
                    FROM chunks c WHERE c.index_config_id = %s
                    ORDER BY c.embedding <=> %s LIMIT %s""",  # noqa: S608 - constant columns
                (embedding, config_id, embedding, limit),
            ).fetchall()
        return [_hit(r) for r in rows]

    def fulltext_search(self, config_id: int, tsquery: str, limit: int) -> list[SearchHit]:
        if not tsquery:
            return []
        rows = self.conn.execute(
            f"""SELECT {_HIT_COLUMNS}, ts_rank_cd(c.tsv, q, 32) AS score
                FROM chunks c, to_tsquery('german', %s) q
                WHERE c.index_config_id = %s AND c.tsv @@ q
                ORDER BY score DESC, c.id LIMIT %s""",  # noqa: S608 - constant columns
            (tsquery, config_id, limit),
        ).fetchall()
        return [_hit(r) for r in rows]

    # --- answer lineage -----------------------------------------------------------------------

    def log_answer(
        self,
        question: str,
        mode: str,
        config_id: int | None,
        chunk_ids: Sequence[int],
        answer: str,
        llm_model: str | None,
    ) -> int:
        with self.conn.transaction():
            row = self.conn.execute(
                """INSERT INTO answer_log (question, mode, index_config_id, chunk_ids, answer,
                       llm_model) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (question, mode, config_id, list(chunk_ids), answer, llm_model),
            ).fetchone()
        assert row is not None
        return int(row["id"])
