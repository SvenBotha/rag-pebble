"""Vector store: FAISS `IndexIDMap2` over `IndexFlatIP`, plus SQLite for metadata.

Soft-deletes flip a tombstone column in SQLite. The on-disk FAISS index
is only rewritten by `compact`. Retrieval over-fetches from FAISS and
filters tombstones via a single SQLite query.

A `threading.RLock` serialises all public operations. The store is
constructed once at app startup and shared across requests; the lock
guards against the rare case of concurrent admin commands and request
traffic touching FAISS at the same time.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import faiss
import numpy as np

from pebble.core.errors import StoreError
from pebble.core.interfaces import Chunk, DocumentInfo, RetrievedChunk

_OVERFETCH_MULTIPLIER = 2
_OVERFETCH_FLOOR = 5


class FaissSqliteStore:
    """Concrete `VectorStore` backed by FAISS + SQLite.

    Vectors are expected normalised before insert; the store normalises
    defensively on add so callers cannot accidentally poison similarity
    scores by skipping that step.
    """

    def __init__(self, index_path: Path, metadata_path: Path, dim: int) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.index_path = index_path
        self.metadata_path = metadata_path
        self.dim = dim
        self._lock = threading.RLock()
        self._index: faiss.Index | None = None
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ load

    def load(self) -> None:
        with self._lock:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.metadata_path),
                check_same_thread=False,
                isolation_level="DEFERRED",
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._init_schema(self._conn)

            if self.index_path.exists():
                index = faiss.read_index(str(self.index_path))
                if index.d != self.dim:
                    raise StoreError(
                        f"existing index dim {index.d} does not match configured dim {self.dim}"
                    )
                self._index = index
            else:
                self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(self.dim))

    # ------------------------------------------------------------------ IDs

    def allocate_chunk_ids(self, n: int) -> int:
        if n <= 0:
            raise ValueError("n must be positive")
        conn = self._require_conn()
        with self._lock:
            # Single atomic UPDATE ... RETURNING avoids the read-modify-write
            # race that occurs when multiple processes share the same database.
            cur = conn.execute(
                "UPDATE id_sequence SET next_id = next_id + ? "
                "WHERE name = 'chunk' RETURNING next_id - ?",
                (n, n),
            )
            first = int(cur.fetchone()[0])
            conn.commit()
            return first

    # ------------------------------------------------------------------ writes

    def add(
        self,
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise StoreError(
                f"chunks/vectors length mismatch ({len(chunks)} vs {len(vectors)})"
            )
        if not chunks:
            return

        conn = self._require_conn()
        index = self._require_index()

        rows: list[tuple[object, ...]] = []
        for chunk in chunks:
            if chunk.chunk_id <= 0:
                raise StoreError(
                    f"chunk has unassigned id; allocate_chunk_ids first: {chunk}"
                )
            rows.append(
                (
                    chunk.chunk_id,
                    chunk.doc_id,
                    chunk.source_path,
                    chunk.index,
                    chunk.text,
                    chunk.created_at.isoformat(),
                    json.dumps(chunk.metadata) if chunk.metadata else None,
                )
            )

        vecs = np.asarray(vectors, dtype="float32")
        if vecs.shape != (len(chunks), self.dim):
            raise StoreError(
                f"vectors shape {vecs.shape} does not match (n={len(chunks)}, dim={self.dim})"
            )
        faiss.normalize_L2(vecs)
        ids = np.array([c.chunk_id for c in chunks], dtype="int64")

        with self._lock:
            conn.executemany(
                "INSERT INTO chunks "
                "(chunk_id, doc_id, source_path, chunk_index, text, created_at, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
            index.add_with_ids(vecs, ids)

    def has_document(self, doc_id: str) -> bool:
        conn = self._require_conn()
        with self._lock:
            cur = conn.execute(
                "SELECT 1 FROM chunks WHERE doc_id = ? AND deleted = 0 LIMIT 1",
                (doc_id,),
            )
            return cur.fetchone() is not None

    def delete_document(self, doc_id: str) -> int:
        conn = self._require_conn()
        with self._lock:
            cur = conn.execute(
                "UPDATE chunks SET deleted = 1 WHERE doc_id = ? AND deleted = 0",
                (doc_id,),
            )
            conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------ read

    def search(
        self,
        vector: Sequence[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        if top_k <= 0:
            return []
        conn = self._require_conn()
        index = self._require_index()

        with self._lock:
            ntotal = index.ntotal
            if ntotal == 0:
                return []

            overfetch = min(top_k * _OVERFETCH_MULTIPLIER + _OVERFETCH_FLOOR, ntotal)
            query = np.asarray([vector], dtype="float32")
            if query.shape != (1, self.dim):
                raise StoreError(
                    f"query vector shape {query.shape} does not match dim {self.dim}"
                )
            faiss.normalize_L2(query)
            scores, ids = index.search(query, overfetch)

            candidate_ids = [int(i) for i in ids[0].tolist() if i != -1]
            if not candidate_ids:
                return []

            placeholders = ",".join("?" * len(candidate_ids))
            cur = conn.execute(
                f"SELECT chunk_id, doc_id, source_path, chunk_index, text, "
                f"created_at, metadata FROM chunks "
                f"WHERE chunk_id IN ({placeholders}) AND deleted = 0",
                candidate_ids,
            )
            live = {row[0]: row for row in cur.fetchall()}

        results: list[RetrievedChunk] = []
        for score, cid in zip(scores[0].tolist(), ids[0].tolist(), strict=True):
            if cid == -1:
                continue
            row = live.get(int(cid))
            if row is None:
                continue
            chunk = Chunk(
                chunk_id=row[0],
                doc_id=row[1],
                source_path=row[2],
                index=row[3],
                text=row[4],
                created_at=datetime.fromisoformat(row[5]),
                metadata=json.loads(row[6]) if row[6] else {},
            )
            results.append(RetrievedChunk(chunk=chunk, score=float(score)))
            if len(results) >= top_k:
                break
        return results

    # ------------------------------------------------------------------ list

    def list_documents(self) -> list[DocumentInfo]:
        conn = self._require_conn()
        with self._lock:
            cur = conn.execute(
                "SELECT doc_id, source_path, COUNT(*) AS chunk_count, "
                "MIN(created_at) AS created_at "
                "FROM chunks WHERE deleted = 0 "
                "GROUP BY doc_id ORDER BY MIN(created_at) DESC"
            )
            return [
                DocumentInfo(
                    doc_id=row[0],
                    source_path=row[1],
                    chunk_count=row[2],
                    created_at=row[3],
                )
                for row in cur.fetchall()
            ]

    # ------------------------------------------------------------------ compact

    def compact(self) -> None:
        conn = self._require_conn()
        with self._lock:
            old_index = self._require_index()
            cur = conn.execute(
                "SELECT chunk_id FROM chunks WHERE deleted = 0 ORDER BY chunk_id"
            )
            live_ids = [int(row[0]) for row in cur.fetchall()]
            new_index = faiss.IndexIDMap2(faiss.IndexFlatIP(self.dim))

            if live_ids:
                vectors = np.array(
                    [old_index.reconstruct(cid) for cid in live_ids],
                    dtype="float32",
                )
                new_index.add_with_ids(vectors, np.array(live_ids, dtype="int64"))

            self._index = new_index
            conn.execute("DELETE FROM chunks WHERE deleted = 1")
            conn.commit()
            faiss.write_index(new_index, str(self.index_path))

    # ------------------------------------------------------------------ persist

    def persist(self) -> None:
        index = self._require_index()
        with self._lock:
            faiss.write_index(index, str(self.index_path))

    @property
    def live_count(self) -> int:
        conn = self._require_conn()
        with self._lock:
            cur = conn.execute("SELECT COUNT(*) FROM chunks WHERE deleted = 0")
            return int(cur.fetchone()[0])

    # ------------------------------------------------------------------ internals

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StoreError("store not loaded; call load() first")
        return self._conn

    def _require_index(self) -> faiss.Index:
        if self._index is None:
            raise StoreError("store not loaded; call load() first")
        return self._index

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id INTEGER PRIMARY KEY,
                doc_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                metadata TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_deleted ON chunks(deleted);
            CREATE TABLE IF NOT EXISTS id_sequence (
                name TEXT PRIMARY KEY,
                next_id INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO id_sequence (name, next_id) VALUES ('chunk', 1);
            """
        )
        conn.commit()
