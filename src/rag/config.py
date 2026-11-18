"""Central configuration, read from environment variables prefixed with ``RAG_``."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LawSelection(BaseModel):
    """One law to ingest, identified by its URL slug on gesetze-im-internet.de.

    ``ranges`` restricts ingestion to paragraph ranges (inclusive), e.g. ``[("312", "361")]``.
    ``None`` means the whole law.
    """

    slug: str
    ranges: list[tuple[str, str]] | None = None

    @field_validator("slug")
    @classmethod
    def _slug_is_simple(cls, value: str) -> str:
        if not value or not all(c.isalnum() or c in "_-" for c in value):
            raise ValueError(f"invalid law slug: {value!r}")
        return value


# Consumer-relevant parts of the BGB; the other laws are ingested completely.
DEFAULT_LAWS: list[LawSelection] = [
    LawSelection(
        slug="bgb",
        ranges=[
            ("13", "14"),  # consumer / entrepreneur
            ("241", "361"),  # obligations, T&Cs, consumer contracts, withdrawal, digital products
            ("433", "480"),  # sale of goods incl. consumer sale
            ("488", "515"),  # consumer credit
            ("535", "580a"),  # tenancy
            ("631", "651y"),  # contracts for work, package travel
        ],
    ),
    LawSelection(slug="evo_2023"),
    LawSelection(slug="pangv_2022"),
    LawSelection(slug="enwg_2005"),
    LawSelection(slug="tkg_2021"),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore")

    log_level: str = "INFO"

    # Sources
    law_base_url: str = "https://www.gesetze-im-internet.de"
    laws: list[LawSelection] = Field(default_factory=lambda: list(DEFAULT_LAWS))
    http_timeout_s: float = 60.0
    user_agent: str = "consumer-rights-rag/0.1 (+https://github.com/riodeb21195)"

    # Storage
    database_url: str = "postgresql://rag:rag@localhost:5432/rag"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_bucket: str = "raw-laws"

    # Processing
    chunking_strategy: Literal["paragraph", "absatz"] = "paragraph"
    chunk_max_chars: int = 2000
    chunk_min_chars: int = 20
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 384
    embedding_batch_size: int = 16

    # Retrieval
    retrieval_mode: Literal["vector", "fulltext", "hybrid"] = "hybrid"
    top_k: int = 5
    rrf_k: int = 60
    candidate_pool: int = 30
    rerank_enabled: bool = False
    rerank_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"

    # Optional LLM
    llm_enabled: bool = False
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:1.5b"
    llm_timeout_s: float = 120.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
