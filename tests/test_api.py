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
    app.state.ingest_active = False
    app.state.ingest_queue = None
    app.state.config_path = None
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


def test_cross_doc_batching_ingests_all_chunks(
    tmp_path: Path, stub_embedder: StubEmbedder, stub_llm: StubLLM
) -> None:
    """Batching across docs must not drop chunks at batch boundaries."""
    # Use a tiny batch_size so we exercise the flush-mid-loop path.
    config = PebbleConfig()
    store = FaissSqliteStore(
        index_path=tmp_path / "b.index",
        metadata_path=tmp_path / "b.meta.sqlite",
        dim=STUB_DIM,
    )
    store.load()
    from pebble.core.chunking import RecursiveCharacterChunker
    from pebble.core.pipeline import IngestPipeline

    chunker = RecursiveCharacterChunker(chunk_size=50, overlap=5)
    ingest = IngestPipeline(
        chunker=chunker,
        embedder=stub_embedder,  # type: ignore[arg-type]
        store=store,
        sources=config.sources,
        limits=config.limits,
        embed_batch_size=3,  # tiny batch — forces mid-loop flushes
    )

    # Write 5 docs, each producing ~3 chunks at chunk_size=50.
    for i in range(5):
        (tmp_path / f"doc{i}.md").write_text(f"word{i} " * 40)

    import asyncio
    result = asyncio.run(ingest.ingest_paths([tmp_path]))
    assert result.ingested_documents == 5
    assert result.ingested_chunks == store.live_count
    assert result.ingested_chunks > 0


def test_reingest_same_path_does_not_duplicate(client: TestClient, tmp_path: Path):
    src = tmp_path / "a.md"
    src.write_text("hello world. " * 20)
    r1 = client.post("/ingest", json={"paths": [str(tmp_path)]})
    assert r1.status_code == 200
    chunks_first = r1.json()["ingested_chunks"]

    r2 = client.post("/ingest", json={"paths": [str(tmp_path)]})
    assert r2.status_code == 200
    assert r2.json()["ingested_documents"] == 0
    assert r2.json()["already_ingested"] == 1
    assert r2.json()["ingested_chunks"] == 0

    # Total chunks in store unchanged after second ingest.
    r = client.get("/ready")
    assert r.json()["index_size"] == chunks_first


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


# ---------------------------------------------------------------------------
# GET /documents
# ---------------------------------------------------------------------------


def test_list_documents_empty(client: TestClient) -> None:
    r = client.get("/documents")
    assert r.status_code == 200
    body = r.json()
    assert body["documents"] == []
    assert body["total"] == 0


def test_list_documents_after_ingest(client: TestClient, tmp_path: Path) -> None:
    src = tmp_path / "hello.md"
    src.write_text("hello world. " * 20)
    client.post("/ingest", json={"paths": [str(tmp_path)]})

    r = client.get("/documents")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    doc = body["documents"][0]
    assert doc["source_path"] == str(src)
    assert doc["chunk_count"] >= 1
    assert "created_at" in doc


# ---------------------------------------------------------------------------
# GET /config + POST /config
# ---------------------------------------------------------------------------


def test_get_config(client: TestClient) -> None:
    r = client.get("/config")
    assert r.status_code == 200
    cfg = r.json()["config"]
    assert "llm" in cfg
    assert "retrieval" in cfg
    assert "embeddings" in cfg


def test_post_config_updates_field(
    test_app: FastAPI, tmp_path: Path, client: TestClient
) -> None:
    config_yaml = tmp_path / "config.yaml"
    import yaml as _yaml

    config_yaml.write_text(_yaml.dump({"llm": {"model": "gpt-4o-mini"}}), encoding="utf-8")
    test_app.state.config_path = config_yaml

    r = client.post("/config", json={"llm": {"model": "gpt-4o"}})
    assert r.status_code == 200
    assert r.json()["config"]["llm"]["model"] == "gpt-4o"

    saved = _yaml.safe_load(config_yaml.read_text())
    assert saved["llm"]["model"] == "gpt-4o"


def test_post_config_rejects_invalid(client: TestClient) -> None:
    r = client.post("/config", json={"retrieval": {"top_k": -1}})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /admin/reload
# ---------------------------------------------------------------------------


def test_admin_reload(
    test_app: FastAPI, tmp_path: Path, stub_embedder: StubEmbedder, stub_llm: StubLLM
) -> None:
    import os

    import yaml as _yaml

    os.environ.setdefault("OPENAI_API_KEY", "sk-test")

    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        _yaml.dump({"storage": {"pods_dir": str(tmp_path / "pods"), "active_pod": "default"}}),
        encoding="utf-8",
    )
    test_app.state.config_path = config_yaml

    with TestClient(test_app) as c:
        r = c.post("/admin/reload")
    assert r.status_code == 200
    assert r.json()["reloaded"] is True


# ---------------------------------------------------------------------------
# GET /ingest/stream (SSE)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_stream_events(test_app: FastAPI, tmp_path: Path) -> None:
    import asyncio
    import json as _json

    import httpx

    src = tmp_path / "stream_test.md"
    src.write_text("foo bar baz. " * 30)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:

        async def consume_stream() -> list[dict]:
            events: list[dict] = []
            async with ac.stream("GET", "/ingest/stream") as stream_resp:
                async for line in stream_resp.aiter_lines():
                    if line.startswith("data:"):
                        events.append(_json.loads(line[5:].strip()))
                        if events[-1]["type"] in ("complete", "error"):
                            break
            return events

        stream_task = asyncio.create_task(consume_stream())
        # Yield control so the SSE endpoint can run and create the queue.
        await asyncio.sleep(0.05)

        ingest_resp = await ac.post("/ingest", json={"paths": [str(tmp_path)]})
        assert ingest_resp.status_code == 200

        events = await stream_task

    types = [e["type"] for e in events]
    assert "complete" in types


def test_ingest_409_when_active(test_app: FastAPI, tmp_path: Path) -> None:
    test_app.state.ingest_active = True
    with TestClient(test_app) as c:
        r = c.post("/ingest", json={"paths": [str(tmp_path)]})
    assert r.status_code == 409
    test_app.state.ingest_active = False
