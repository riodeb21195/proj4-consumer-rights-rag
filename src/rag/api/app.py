"""FastAPI service: search, answers with citations, lineage, evaluation results, metrics."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Protocol

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pgvector.psycopg import register_vector
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from rag.api.metrics import ERRORS, LATENCY, REQUESTS, RETRIEVED, EvalCollector, load_results
from rag.config import Settings, get_settings
from rag.logging import configure_logging
from rag.process.embed import Embedder, make_embedder
from rag.retrieval.generate import Answer, ExtractiveGenerator, OllamaGenerator, citation
from rag.retrieval.search import Mode, NoActiveIndexError, Reranker, Searcher
from rag.store.vector_store import SearchHit, VectorStore

log = logging.getLogger(__name__)


class Generator(Protocol):
    def answer(self, question: str, hits: list[SearchHit]) -> Answer: ...


@dataclass
class Services:
    settings: Settings
    pool: ConnectionPool[psycopg.Connection[dict[str, Any]]]
    embedder: Embedder
    generator: Generator
    reranker: Reranker | None = None

    @contextmanager
    def store(self) -> Iterator[VectorStore]:
        with self.pool.connection() as conn:
            yield VectorStore(conn)

    def searcher(self, store: VectorStore) -> Searcher:
        return Searcher(
            store,
            self.embedder,
            candidate_pool=self.settings.candidate_pool,
            rrf_k=self.settings.rrf_k,
            reranker=self.reranker,
        )


def _configure_conn(conn: psycopg.Connection[Any]) -> None:
    register_vector(conn)


def build_services(settings: Settings) -> Services:
    pool: ConnectionPool[psycopg.Connection[dict[str, Any]]] = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=4,
        kwargs={"autocommit": True, "row_factory": dict_row},
        configure=_configure_conn,
        open=True,
    )
    embedder = make_embedder(settings.embedding_model, settings.embedding_batch_size)
    reranker: Reranker | None = None
    if settings.rerank_enabled:
        from rag.retrieval.rerank import CrossEncoderReranker

        reranker = CrossEncoderReranker(settings.rerank_model)
    generator: Generator = (
        OllamaGenerator(settings.ollama_url, settings.ollama_model)
        if settings.llm_enabled
        else ExtractiveGenerator()
    )
    return Services(settings, pool, embedder, generator, reranker)


def _services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc


# Module level so FastAPI can resolve the (postponed) annotation.
Svc = Annotated[Services, Depends(_services)]


# Request/response schemas


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    k: int = Field(default=5, ge=1, le=50)
    mode: Mode | None = None


class Source(BaseModel):
    n: int
    citation: str
    law: str
    law_slug: str
    paragraph: str
    absatz: str | None
    heading: str
    stand: str
    url: str
    text: str
    score: float
    chunk_id: int
    law_version_id: int


class SearchResponse(BaseModel):
    mode: str
    sources: list[Source]


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    k: int = Field(default=5, ge=1, le=20)
    mode: Mode | None = None


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    mode: str
    llm_model: str | None
    answer_id: int


def _sources(hits: list[SearchHit]) -> list[Source]:
    return [
        Source(
            n=n,
            citation=citation(h),
            law=h.law_abbreviation,
            law_slug=h.law_slug,
            paragraph=h.paragraph,
            absatz=h.absatz,
            heading=h.heading,
            stand=h.stand,
            url=h.source_url,
            text=h.text,
            score=h.score,
            chunk_id=h.chunk_id,
            law_version_id=h.law_version_id,
        )
        for n, h in enumerate(hits, start=1)
    ]


def create_app(
    settings: Settings | None = None,
    services_factory: Callable[[Settings], Services] = build_services,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        app.state.services = services_factory(settings)
        collector = EvalCollector(Path(settings.eval_results_dir), settings.eval_hit_rate_threshold)
        REGISTRY.register(collector)
        log.info("api started", extra={"model": settings.embedding_model})
        yield
        REGISTRY.unregister(collector)
        app.state.services.pool.close()

    app = FastAPI(title="Consumer Rights RAG", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            # Label by route template ("/lineage/{answer_id}") to keep metric cardinality low.
            route = request.scope.get("route")
            endpoint = getattr(route, "path", "unmatched")
            LATENCY.labels(endpoint).observe(time.perf_counter() - started)
            REQUESTS.labels(request.method, endpoint, str(status)).inc()
            if status >= 500:
                ERRORS.labels(endpoint).inc()

    @app.get("/health")
    def health(svc: Svc) -> dict[str, Any]:
        with svc.store() as store:
            active = store.active_config()
        return {
            "status": "ok",
            "embedding_model": svc.embedder.model_name,
            "active_index": active.__dict__ if active else None,
            "llm_enabled": svc.settings.llm_enabled,
        }

    @app.post("/search")
    def search(req: SearchRequest, svc: Svc) -> SearchResponse:
        mode = req.mode or svc.settings.retrieval_mode
        with svc.store() as store:
            try:
                hits = svc.searcher(store).search(req.query, mode=mode, k=req.k)
            except NoActiveIndexError as exc:
                raise HTTPException(503, str(exc)) from exc
        return SearchResponse(mode=mode, sources=_sources(hits))

    @app.post("/ask")
    def ask(req: AskRequest, svc: Svc) -> AskResponse:
        mode = req.mode or svc.settings.retrieval_mode
        with svc.store() as store:
            try:
                searcher = svc.searcher(store)
                config_id = searcher.resolve_config(None)
                hits = searcher.search(req.question, mode=mode, k=req.k, config_id=config_id)
            except NoActiveIndexError as exc:
                raise HTTPException(503, str(exc)) from exc
            answer = svc.generator.answer(req.question, hits)
            answer_id = store.log_answer(
                req.question,
                mode,
                config_id,
                [h.chunk_id for h in hits],
                answer.text,
                answer.llm_model,
            )
        RETRIEVED.observe(len(hits))
        return AskResponse(
            answer=answer.text,
            sources=_sources(hits),
            mode=mode,
            llm_model=answer.llm_model,
            answer_id=answer_id,
        )

    @app.get("/lineage/{answer_id}")
    def lineage(answer_id: int, svc: Svc) -> dict[str, Any]:
        with svc.store() as store:
            row = store.conn.execute(
                "SELECT * FROM answer_log WHERE id = %s", (answer_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(404, "unknown answer id")
            chunks = store.get_chunks(row["chunk_ids"])
        return {"answer": row, "chunks": chunks}

    @app.get("/evaluation")
    def evaluation(svc: Svc) -> list[dict[str, Any]]:
        return load_results(Path(svc.settings.eval_results_dir))

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    return app


def main() -> None:  # pragma: no cover - started by uvicorn in the container
    import uvicorn

    uvicorn.run("rag.api.app:create_app", factory=True, host="0.0.0.0", port=8000)  # noqa: S104
