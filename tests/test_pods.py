"""Tests for the Pods feature: core module, API endpoints, and backward compat."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pebble.api.routes import router
from pebble.bootstrap import Services
from pebble.config.schema import PebbleConfig, StorageConfig
from pebble.core.chunking import RecursiveCharacterChunker
from pebble.core.errors import StoreError
from pebble.core.pipeline import IngestPipeline, QueryPipeline
from pebble.core.pods import create_pod, delete_pod, list_pods, write_active_pod
from pebble.core.retrieval import VectorRetriever
from pebble.core.store import FaissSqliteStore
from tests.conftest import STUB_DIM, StubEmbedder, StubLLM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(tmp_path: Path, stub_embedder: StubEmbedder, stub_llm: StubLLM) -> FastAPI:
    pods_dir = tmp_path / "pods"
    pods_dir.mkdir()
    config = PebbleConfig(storage=StorageConfig(pods_dir=pods_dir, active_pod="default"))
    store = FaissSqliteStore(
        index_path=config.storage.resolved_index_path,
        metadata_path=config.storage.resolved_metadata_path,
        dim=STUB_DIM,
    )
    store.load()
    chunker = RecursiveCharacterChunker(
        chunk_size=config.chunking.chunk_size,
        overlap=config.chunking.overlap,
    )
    retriever = VectorRetriever(embedder=stub_embedder, store=store)  # type: ignore[arg-type]
    ingest = IngestPipeline(
        chunker=chunker,
        embedder=stub_embedder,  # type: ignore[arg-type]
        store=store,
        sources=config.sources,
        limits=config.limits,
    )
    query = QueryPipeline(
        retriever=retriever,
        llm=stub_llm,  # type: ignore[arg-type]
        store=store,
        llm_config=config.llm,
        retrieval_config=config.retrieval,
    )
    services = Services(
        config=config,
        http_client=httpx.AsyncClient(),
        embedder=stub_embedder,  # type: ignore[arg-type]
        llm=stub_llm,  # type: ignore[arg-type]
        store=store,
        retriever=retriever,
        ingest=ingest,
        query=query,
    )
    app = FastAPI()
    app.include_router(router)
    app.state.start_time = time.time()
    app.state.services = services
    app.state.ready = True
    app.state.ready_error = None
    app.state.config_path = None
    return app


# ---------------------------------------------------------------------------
# Core module tests
# ---------------------------------------------------------------------------


def test_create_and_list_pods(tmp_path: Path) -> None:
    pods_dir = tmp_path / "pods"
    pods_dir.mkdir()
    create_pod(pods_dir, "alpha")
    create_pod(pods_dir, "beta")
    pods = list_pods(pods_dir, active_pod="alpha")
    names = [p.name for p in pods]
    assert "alpha" in names
    assert "beta" in names
    assert next(p for p in pods if p.name == "alpha").active is True
    assert next(p for p in pods if p.name == "beta").active is False


def test_create_duplicate_raises(tmp_path: Path) -> None:
    pods_dir = tmp_path / "pods"
    pods_dir.mkdir()
    create_pod(pods_dir, "mypod")
    with pytest.raises(StoreError, match="already exists"):
        create_pod(pods_dir, "mypod")


def test_delete_pod(tmp_path: Path) -> None:
    pods_dir = tmp_path / "pods"
    pods_dir.mkdir()
    create_pod(pods_dir, "todelete")
    delete_pod(pods_dir, "todelete")
    pods = list_pods(pods_dir, active_pod="other")
    assert not any(p.name == "todelete" for p in pods)


def test_delete_nonexistent_raises(tmp_path: Path) -> None:
    pods_dir = tmp_path / "pods"
    pods_dir.mkdir()
    with pytest.raises(StoreError, match="does not exist"):
        delete_pod(pods_dir, "ghost")


def test_name_validation_rejects_path_traversal(tmp_path: Path) -> None:
    pods_dir = tmp_path / "pods"
    pods_dir.mkdir()
    for bad_name in ["../evil", "foo/bar", ".hidden", "", "a" * 65]:
        with pytest.raises(StoreError):
            create_pod(pods_dir, bad_name)


def test_name_validation_rejects_path_traversal_on_delete(tmp_path: Path) -> None:
    pods_dir = tmp_path / "pods"
    pods_dir.mkdir()
    with pytest.raises(StoreError):
        delete_pod(pods_dir, "../evil")


def test_list_pods_empty_when_dir_missing(tmp_path: Path) -> None:
    pods = list_pods(tmp_path / "nonexistent", active_pod="default")
    assert pods == []


def test_list_pods_chunk_count(tmp_path: Path) -> None:
    """Pods with no SQLite file report 0 chunks."""
    pods_dir = tmp_path / "pods"
    pods_dir.mkdir()
    create_pod(pods_dir, "empty")
    pods = list_pods(pods_dir, active_pod="empty")
    assert pods[0].chunk_count == 0


def test_write_active_pod_no_config_is_noop(tmp_path: Path) -> None:
    write_active_pod(None, "mypod")  # should not raise


def test_write_active_pod_updates_yaml(tmp_path: Path) -> None:
    import yaml

    cfg = tmp_path / "config.yaml"
    cfg.write_text("storage:\n  active_pod: old\n")
    write_active_pod(cfg, "newpod")
    raw = yaml.safe_load(cfg.read_text())
    assert raw["storage"]["active_pod"] == "newpod"
    assert "index_path" not in raw.get("storage", {})


def test_write_active_pod_removes_deprecated_fields(tmp_path: Path) -> None:
    import yaml

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "storage:\n  index_path: ./old.index\n  metadata_path: ./old.sqlite\n"
    )
    write_active_pod(cfg, "newpod")
    raw = yaml.safe_load(cfg.read_text())
    assert raw["storage"]["active_pod"] == "newpod"
    assert "index_path" not in raw["storage"]
    assert "metadata_path" not in raw["storage"]


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
def pods_client(
    tmp_path: Path, stub_embedder: StubEmbedder, stub_llm: StubLLM
) -> TestClient:
    return TestClient(_make_app(tmp_path, stub_embedder, stub_llm))


def test_pods_api_list_returns_default_pod(pods_client: TestClient) -> None:
    """The store load() creates the active pod directory, so it appears in the list."""
    r = pods_client.get("/pods")
    assert r.status_code == 200
    pods = r.json()
    assert any(p["name"] == "default" and p["active"] is True for p in pods)


def test_pods_api_create(pods_client: TestClient) -> None:
    r = pods_client.post("/pods", json={"name": "mypod"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "mypod"
    assert body["created"] is True

    r2 = pods_client.get("/pods")
    assert r2.status_code == 200
    names = [p["name"] for p in r2.json()]
    assert "mypod" in names


def test_pods_api_create_duplicate_returns_409(pods_client: TestClient) -> None:
    pods_client.post("/pods", json={"name": "dupe"})
    r = pods_client.post("/pods", json={"name": "dupe"})
    assert r.status_code == 409


def test_pods_api_delete(pods_client: TestClient) -> None:
    pods_client.post("/pods", json={"name": "gonepod"})
    r = pods_client.delete("/pods/gonepod")
    assert r.status_code == 200

    r2 = pods_client.get("/pods")
    names = [p["name"] for p in r2.json()]
    assert "gonepod" not in names


def test_pods_api_delete_nonexistent_returns_404(pods_client: TestClient) -> None:
    r = pods_client.delete("/pods/doesnotexist")
    assert r.status_code == 404


def test_pods_api_delete_active_refused(pods_client: TestClient) -> None:
    r = pods_client.delete("/pods/default")
    assert r.status_code == 409


def test_pods_api_activate(pods_client: TestClient, tmp_path: Path) -> None:
    pods_client.post("/pods", json={"name": "v2"})
    r = pods_client.post("/pods/v2/activate")
    assert r.status_code == 202
    assert "v2" in r.json()["message"]


def test_pods_api_activate_nonexistent_returns_404(pods_client: TestClient) -> None:
    r = pods_client.post("/pods/ghost/activate")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Backward compatibility: old index_path / metadata_path still work
# ---------------------------------------------------------------------------


def test_backward_compat_explicit_paths(tmp_path: Path) -> None:
    index_path = tmp_path / "old.index"
    meta_path = tmp_path / "old.meta.sqlite"
    config = PebbleConfig(
        storage=StorageConfig(index_path=index_path, metadata_path=meta_path)
    )
    assert config.storage.resolved_index_path == index_path
    assert config.storage.resolved_metadata_path == meta_path


def test_default_storage_uses_pod_paths(tmp_path: Path) -> None:
    config = PebbleConfig(
        storage=StorageConfig(pods_dir=tmp_path / "pods", active_pod="mypod")
    )
    expected_index = tmp_path / "pods" / "mypod" / "pebble.index"
    expected_meta = tmp_path / "pods" / "mypod" / "pebble.meta.sqlite"
    assert config.storage.resolved_index_path == expected_index
    assert config.storage.resolved_metadata_path == expected_meta
