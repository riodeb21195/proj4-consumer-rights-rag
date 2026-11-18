-- Schema for the consumer-rights RAG index. Idempotent: safe to run on every start.
-- Lineage: ingest_runs -> law_versions (raw XML in MinIO) -> norms -> chunks -> answer_log.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ingest_runs (
    id            bigserial PRIMARY KEY,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running', 'success', 'partial', 'failed')),
    trigger       text NOT NULL DEFAULT 'manual',
    index_config_id integer,
    stats         jsonb NOT NULL DEFAULT '{}'::jsonb,
    errors        jsonb NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS laws (
    slug          text PRIMARY KEY,
    abbreviation  text NOT NULL,
    title         text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Every distinct XML we have seen for a law. Exactly one per law is current (= indexed).
CREATE TABLE IF NOT EXISTS law_versions (
    id             bigserial PRIMARY KEY,
    law_slug       text NOT NULL REFERENCES laws (slug) ON DELETE CASCADE,
    builddate      timestamp NOT NULL,
    stand          text NOT NULL DEFAULT '',
    xml_sha256     text NOT NULL,
    raw_object_key text NOT NULL,
    source_url     text NOT NULL,
    etag           text,
    last_modified  text,
    ingest_run_id  bigint REFERENCES ingest_runs (id) ON DELETE SET NULL,
    fetched_at     timestamptz NOT NULL DEFAULT now(),
    is_current     boolean NOT NULL DEFAULT false,
    UNIQUE (law_slug, xml_sha256)
);
CREATE UNIQUE INDEX IF NOT EXISTS law_versions_one_current
    ON law_versions (law_slug) WHERE is_current;

-- Current text of every indexed provision. Repealed or removed provisions are deleted.
CREATE TABLE IF NOT EXISTS norms (
    id             bigserial PRIMARY KEY,
    law_slug       text NOT NULL REFERENCES laws (slug) ON DELETE CASCADE,
    norm_key       text NOT NULL,          -- e.g. "§ 312g", "Anlage"
    doknr          text NOT NULL,
    title          text NOT NULL DEFAULT '',
    section        text NOT NULL DEFAULT '',
    absaetze       jsonb NOT NULL,
    content_hash   text NOT NULL,
    law_version_id bigint NOT NULL REFERENCES law_versions (id),
    source_url     text NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (law_slug, norm_key)
);

-- Chunking strategy + embedding model. Chunks are always tied to the config that produced them,
-- so changing either creates a new config and triggers a full re-index.
CREATE TABLE IF NOT EXISTS index_configs (
    id                serial PRIMARY KEY,
    chunking_strategy text NOT NULL,
    chunking_version  text NOT NULL,
    embedding_model   text NOT NULL,
    embedding_dim     integer NOT NULL,
    is_active         boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (chunking_strategy, chunking_version, embedding_model)
);
CREATE UNIQUE INDEX IF NOT EXISTS index_configs_one_active
    ON index_configs (is_active) WHERE is_active;

CREATE TABLE IF NOT EXISTS chunks (
    id                bigserial PRIMARY KEY,
    index_config_id   integer NOT NULL REFERENCES index_configs (id) ON DELETE CASCADE,
    norm_id           bigint NOT NULL REFERENCES norms (id) ON DELETE CASCADE,
    chunk_index       integer NOT NULL,
    law_slug          text NOT NULL,
    law_abbreviation  text NOT NULL,
    paragraph         text NOT NULL,
    absatz            text,
    heading           text NOT NULL DEFAULT '',
    text              text NOT NULL,       -- what users see
    embed_text        text NOT NULL,       -- text + context prefix that was embedded / indexed
    content_hash      text NOT NULL,
    norm_content_hash text NOT NULL,
    stand             text NOT NULL DEFAULT '',
    source_url        text NOT NULL,
    law_version_id    bigint NOT NULL REFERENCES law_versions (id),
    embedding         vector(384) NOT NULL,
    tsv               tsvector GENERATED ALWAYS AS (to_tsvector('german', embed_text)) STORED,
    created_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (index_config_id, norm_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS chunks_config_idx ON chunks (index_config_id);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);

-- Which chunks were shown for which question (Gesetz -> Chunk -> Antwort).
CREATE TABLE IF NOT EXISTS answer_log (
    id              bigserial PRIMARY KEY,
    asked_at        timestamptz NOT NULL DEFAULT now(),
    question        text NOT NULL,
    mode            text NOT NULL,
    index_config_id integer REFERENCES index_configs (id) ON DELETE SET NULL,
    chunk_ids       bigint[] NOT NULL,
    answer          text NOT NULL,
    llm_model       text
);
