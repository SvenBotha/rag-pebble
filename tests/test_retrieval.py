"""Tests for the FAISS + SQLite vector store.

Exercises real FAISS and SQLite against a per-test temp directory.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from pebble.core.errors import StoreError
from pebble.core.interfaces import UNASSIGNED_CHUNK_ID, Chunk
from pebble.core.store import FaissSqliteStore

DIM = 16


def _chunk(text: str, doc_id: str = "d1", idx: int = 0) -> Chunk:
    return Chunk(
        chunk_id=UNASSIGNED_CHUNK_ID,
        doc_id=doc_id,
        text=text,
        index=idx,
        source_path=f"/tmp/{doc_id}.md",
        created_at=datetime.now(UTC),
        metadata={},
    )


def _rand_vec(seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(DIM).astype("float32").tolist()


@pytest.fixture
def store(tmp_store_paths: tuple[Path, Path]) -> FaissSqliteStore:
    index_path, meta_path = tmp_store_paths
    s = FaissSqliteStore(index_path=index_path, metadata_path=meta_path, dim=DIM)
    s.load()
    return s


def test_load_creates_fresh_index(store: FaissSqliteStore):
    assert store.live_count == 0


def test_allocate_chunk_ids_is_contiguous(store: FaissSqliteStore):
    a = store.allocate_chunk_ids(3)
    b = store.allocate_chunk_ids(2)
    assert b == a + 3


def test_add_and_search_round_trip(store: FaissSqliteStore):
    chunks_in = [
        replace(_chunk(f"text-{i}"), chunk_id=store.allocate_chunk_ids(1))
        for i in range(5)
    ]
    vectors = [_rand_vec(i) for i in range(5)]
    store.add(chunks_in, vectors)

    assert store.live_count == 5
    hits = store.search(vectors[2], top_k=1)
    assert len(hits) == 1
    assert hits[0].chunk.text == "text-2"
    # Score should be close to 1.0 (vector matches itself after normalisation).
    assert hits[0].score > 0.99


def test_delete_document_hides_chunks_from_search(store: FaissSqliteStore):
    first_id = store.allocate_chunk_ids(4)
    chunks_in = [
        replace(_chunk(f"keep-{i}", doc_id="keep"), chunk_id=first_id + i)
        for i in range(2)
    ] + [
        replace(_chunk(f"drop-{i}", doc_id="drop"), chunk_id=first_id + 2 + i)
        for i in range(2)
    ]
    vectors = [_rand_vec(i) for i in range(4)]
    store.add(chunks_in, vectors)

    assert store.live_count == 4
    deleted = store.delete_document("drop")
    assert deleted == 2
    assert store.live_count == 2

    # Drop's vector is gone from search even though FAISS still holds it.
    hits = store.search(vectors[2], top_k=5)
    assert all(h.chunk.doc_id == "keep" for h in hits)


def test_delete_idempotent(store: FaissSqliteStore):
    first_id = store.allocate_chunk_ids(2)
    chunks_in = [
        replace(_chunk(f"x-{i}", doc_id="d"), chunk_id=first_id + i) for i in range(2)
    ]
    store.add(chunks_in, [_rand_vec(i) for i in range(2)])
    assert store.delete_document("d") == 2
    assert store.delete_document("d") == 0


def test_compact_purges_tombstones_and_persists(
    tmp_store_paths: tuple[Path, Path],
):
    index_path, meta_path = tmp_store_paths
    store = FaissSqliteStore(index_path=index_path, metadata_path=meta_path, dim=DIM)
    store.load()

    first_id = store.allocate_chunk_ids(4)
    chunks_in = [
        replace(_chunk(f"keep-{i}", doc_id="keep"), chunk_id=first_id + i)
        for i in range(2)
    ] + [
        replace(_chunk(f"drop-{i}", doc_id="drop"), chunk_id=first_id + 2 + i)
        for i in range(2)
    ]
    vectors = [_rand_vec(i) for i in range(4)]
    store.add(chunks_in, vectors)
    store.delete_document("drop")
    assert store.live_count == 2

    store.compact()
    assert store.live_count == 2
    # After compaction, the deleted rows are physically gone from SQLite.
    conn = store._conn  # noqa: SLF001 — test inspecting internals on purpose
    assert conn is not None
    cur = conn.execute("SELECT COUNT(*) FROM chunks")
    assert cur.fetchone()[0] == 2

    # Persisted on disk: reload a new store and confirm we still see 2 chunks.
    reloaded = FaissSqliteStore(index_path=index_path, metadata_path=meta_path, dim=DIM)
    reloaded.load()
    assert reloaded.live_count == 2


def test_add_rejects_mismatched_lengths(store: FaissSqliteStore):
    first = store.allocate_chunk_ids(1)
    chunk = replace(_chunk("x"), chunk_id=first)
    with pytest.raises(StoreError):
        store.add([chunk], [_rand_vec(0), _rand_vec(1)])


def test_add_rejects_unassigned_chunk_id(store: FaissSqliteStore):
    chunk = _chunk("x")  # chunk_id = UNASSIGNED_CHUNK_ID (-1)
    with pytest.raises(StoreError):
        store.add([chunk], [_rand_vec(0)])


def test_search_with_empty_store_returns_empty(store: FaissSqliteStore):
    assert store.search(_rand_vec(0), top_k=5) == []
