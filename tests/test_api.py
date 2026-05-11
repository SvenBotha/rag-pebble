"""Tests for the HTTP surface using FastAPI's TestClient.

The tests skip the real lifespan and inject a `Services` wired with the
stub embedder/LLM from conftest plus a real `FaissSqliteStore` against
a tmp directory. This keeps the tests offline while still exercising
the real routing, DI, and error-mapping code.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pebble.api.routes import router
from pebble.bootstrap import Services
from pebble.config.schema import (
    LimitsConfig,
    LLMConfig,
    PebbleConfig,
    RetrievalConfig,
)
from pebble.core.chunking import RecursiveCharacterChunker
from pebble.core.pipeline import IngestPipeline, QueryPipeline
from pebble.core.retrieval import VectorRetriever
from pebble.core.store import FaissSqliteStore
from tests.conftest import STUB_DIM, StubEmbedder, StubLLM


def _build_services(
    tmp_path: Path, embedder: StubEmbedder, llm: StubLLM
) -> Services:
    config = PebbleConfig()
    store = FaissSqliteStore(
        index_path=tmp_path / "test.index",
        metadata_path=tmp_path / "test.meta.sqlite",
        dim=STUB_DIM,
    )
    store.load()
    chunker = RecursiveCharacterChunker(
        chunk_size=config.chunking.chunk_size,
        overlap=config.chunking.overlap,
    )
    retriever = VectorRetriever(embedder=embedder, store=store)  # type: ignore[arg-type]
    ingest = IngestPipeline(
        chunker=chunker,
        embedder=embedder,  # type: ignore[arg-type]
        store=store,
        sources=config.sources,
        limits=config.limits,
    )
    query = QueryPipeline(
        retriever=retriever,
        llm=llm,  # type: ignore[arg-type]
        store=store,
        llm_config=config.llm,
        retrieval_config=config.retrieval,
    )
    return Services(
        config=config,
        http_client=httpx.AsyncClient(),
        embedder=embedder,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        store=store,
        retriever=retriever,
        ingest=ingest,
        query=query,
    )


@pytest.fixture
def test_app(tmp_path: Path, stub_embedder: StubEmbedder, stub_llm: StubLLM) -> FastAPI:
    """A FastAPI app with services pre-injected, no lifespan."""
    app = FastAPI()
    app.include_router(router)
    app.state.start_time = time.time()
    app.state.services = _build_services(tmp_path, stub_embedder, stub_llm)
    app.state.ready = True
    app.state.ready_error = None
    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)


def test_health_works_without_services():
    app = FastAPI()
    app.include_router(router)
    app.state.start_time = time.time()
    app.state.services = None
    app.state.ready = False
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "uptime_seconds" in body


def test_ready_503_without_services():
    app = FastAPI()
    app.include_router(router)
    app.state.start_time = time.time()
    app.state.services = None
    app.state.ready = False
    app.state.ready_error = None
    with TestClient(app) as c:
        r = c.get("/ready")
    assert r.status_code == 503
    assert r.json()["ready"] is False


def test_ready_200_with_services(client: TestClient):
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["index_size"] == 0


def test_query_returns_answer_and_no_chunks_without_debug(client: TestClient):
    # Pre-seed via /ingest is heavy; just call the pipeline directly.
    # With an empty index, the route returns the canned "no context" answer.
    r = client.post("/query", json={"query": "hello?"})
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert body["chunks"] == []


def test_query_returns_chunks_when_ingested_and_debug_true(
    client: TestClient, tmp_path: Path
):
    # Drop a file into a temp dir and ingest it via the API.
    src = tmp_path / "a.md"
    src.write_text("hello world. " * 20)
    r = client.post("/ingest", json={"paths": [str(tmp_path)]})
    assert r.status_code == 200, r.text
    assert r.json()["ingested_documents"] >= 1

    r = client.post("/query", json={"query": "hello?", "debug": True})
    assert r.status_code == 200
    body = r.json()
    assert body["chunks"], "expected at least one chunk in debug mode"
    assert "source_path" in body["chunks"][0]


def test_delete_then_query_returns_no_chunks(client: TestClient, tmp_path: Path):
    src = tmp_path / "a.md"
    src.write_text("alpha bravo charlie. " * 20)
    r = client.post("/ingest", json={"paths": [str(tmp_path)]})
    assert r.status_code == 200

    # Compute doc_id the same way the loader does, then delete.
    from pebble.core.ingestion import doc_id_for

    doc_id = doc_id_for(src)
    r = client.delete(f"/documents/{doc_id}")
    assert r.status_code == 200
    deleted = r.json()["deleted_chunks"]
    assert deleted >= 1

    r = client.post("/query", json={"query": "alpha?", "debug": True})
    assert r.status_code == 200
    assert r.json()["chunks"] == []


def test_admin_compact_shrinks_after_delete(client: TestClient, tmp_path: Path):
    src = tmp_path / "a.md"
    src.write_text("foo bar. " * 30)
    client.post("/ingest", json={"paths": [str(tmp_path)]})
    from pebble.core.ingestion import doc_id_for

    client.delete(f"/documents/{doc_id_for(src)}")

    r = client.post("/admin/compact")
    assert r.status_code == 200
    body = r.json()
    assert body["after"] == 0
    assert "elapsed_seconds" in body


def test_query_budget_returns_402(tmp_path: Path, stub_embedder, stub_llm):
    # Build a config with an extremely low query budget.
    config = PebbleConfig(
        limits=LimitsConfig(max_tokens_per_query=10),
        llm=LLMConfig(max_tokens=200),
        retrieval=RetrievalConfig(top_k=5),
    )
    store = FaissSqliteStore(
        index_path=tmp_path / "x.index",
        metadata_path=tmp_path / "x.meta.sqlite",
        dim=STUB_DIM,
    )
    store.load()
    chunker = RecursiveCharacterChunker(
        chunk_size=config.chunking.chunk_size, overlap=config.chunking.overlap
    )
    retriever = VectorRetriever(embedder=stub_embedder, store=store)

    # Use a real OpenAILLM whose budget will trip.
    import os

    from pebble.core.llm import OpenAILLM

    os.environ["OPENAI_API_KEY"] = "sk-test"
    real_llm = OpenAILLM(
        client=httpx.AsyncClient(),
        model=config.llm.model,
        max_tokens_per_query=config.limits.max_tokens_per_query,
    )

    ingest = IngestPipeline(
        chunker=chunker,
        embedder=stub_embedder,
        store=store,
        sources=config.sources,
        limits=config.limits,
    )
    query = QueryPipeline(
        retriever=retriever,
        llm=real_llm,
        store=store,
        llm_config=config.llm,
        retrieval_config=config.retrieval,
    )
    services = Services(
        config=config,
        http_client=httpx.AsyncClient(),
        embedder=stub_embedder,
        llm=real_llm,
        store=store,
        retriever=retriever,
        ingest=ingest,
        query=query,
    )

    # Build app with our budget-limited services.
    from pebble.api.app import _install_error_handlers

    app = FastAPI()
    app.include_router(router)
    app.state.start_time = time.time()
    app.state.services = services
    app.state.ready = True
    app.state.ready_error = None
    _install_error_handlers(app)

    # Ingest something so retrieval has hits to assemble a prompt with.
    src = tmp_path / "a.md"
    src.write_text("the answer is forty-two. " * 50)
    with TestClient(app) as c:
        r = c.post("/ingest", json={"paths": [str(tmp_path)]})
        assert r.status_code == 200
        r = c.post("/query", json={"query": "what is the answer?"})
    assert r.status_code == 402
    assert r.json()["error"] == "budget_exceeded"
