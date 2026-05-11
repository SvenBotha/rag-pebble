"""Protocol contracts between Pebble's subsystems.

These types are the *only* shared surface between ingestion, embedding,
storage, retrieval, generation, and the API/CLI layers. Concrete
implementations live in sibling modules; nothing in this file imports
them. If you find yourself adding a method here, ask first whether a
caller actually needs it — the smallest possible surface is the goal.

Async appears exactly where it earns its place: I/O-bound interfaces
that talk to cloud providers (`Embedder`, `LLMProvider`, `Retriever`).
Local-disk and CPU-bound work (`Chunker`, `DocumentLoader`,
`VectorStore`) is sync — wrapping FAISS or SQLite in asyncio would just
add a thread-pool hop with no concurrency win.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

UNASSIGNED_CHUNK_ID = -1
"""Sentinel value for a Chunk that has not yet been admitted to a VectorStore."""


@dataclass(frozen=True, slots=True)
class Document:
    """A single source document, after loading but before chunking."""

    doc_id: str
    source_path: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Chunk:
    """A unit of retrievable text.

    `chunk_id` is `UNASSIGNED_CHUNK_ID` until the chunk is admitted to a
    VectorStore. The pipeline reserves IDs via `VectorStore.allocate_chunk_ids`
    and rebuilds chunks with real IDs via `dataclasses.replace` before insert.
    """

    chunk_id: int
    doc_id: str
    text: str
    index: int
    source_path: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk: Chunk
    score: float


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class DocumentLoader(Protocol):
    """Reads one path from disk and yields Documents.

    Most implementations yield exactly one Document per file. A PDF loader
    may yield multiple if it splits per page; that choice lives in the
    implementation, not the contract.
    """

    def load(self, path: Path) -> Iterable[Document]: ...


class Chunker(Protocol):
    """Splits a Document into Chunks.

    Yielded Chunks have `chunk_id = UNASSIGNED_CHUNK_ID`. The caller is
    responsible for allocating real IDs via `VectorStore.allocate_chunk_ids`
    before insertion.
    """

    def chunk(self, doc: Document) -> Iterable[Chunk]: ...


# ---------------------------------------------------------------------------
# Embedding & generation
# ---------------------------------------------------------------------------


class Embedder(Protocol):
    """Cloud embedding provider.

    Implementations are expected to enforce batching per config, retry
    transient errors, and raise typed exceptions from `pebble.core.errors`
    (`ProviderTimeoutError`, `ProviderRateLimitError`, `ProviderAuthError`).
    They also enforce `max_embeddings_per_ingest` and raise
    `BudgetExceededError` *before* the network call.
    """

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    @property
    def dim(self) -> int: ...


class LLMProvider(Protocol):
    """Cloud chat-completion provider.

    The Protocol takes `prompt` + `system` separately; the implementation
    decides how to encode them for its provider (e.g. ChatML messages for
    OpenAI). Enforces `max_tokens_per_query` and raises `BudgetExceededError`
    before the network call when the request would exceed it.
    """

    async def complete(
        self,
        prompt: str,
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Storage & retrieval
# ---------------------------------------------------------------------------


class VectorStore(Protocol):
    """Persistent vector store with soft-deletes and explicit compaction.

    Implementations back this with FAISS `IndexIDMap2` plus a SQLite
    metadata table. Deletes are soft — they set a tombstone flag in
    SQLite. `search` filters tombstones at read time and over-fetches
    from FAISS if necessary. `compact` is the only operation that
    rewrites the on-disk FAISS index.
    """

    def allocate_chunk_ids(self, n: int) -> int:
        """Atomically reserve `n` contiguous int64 chunk IDs.

        Returns the first reserved ID. Caller assigns IDs
        `[first, first + n)` and then calls `add`.
        """
        ...

    def add(
        self,
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        """Insert chunks with pre-assigned chunk_ids."""
        ...

    def search(
        self,
        vector: Sequence[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Top-k nearest neighbours, with tombstoned chunks filtered out."""
        ...

    def delete_document(self, doc_id: str) -> int:
        """Soft-delete all chunks for `doc_id`. Returns the count deleted."""
        ...

    def compact(self) -> None:
        """Rebuild the FAISS index from live (non-tombstoned) rows."""
        ...

    def persist(self) -> None: ...

    def load(self) -> None: ...

    @property
    def live_count(self) -> int:
        """Number of non-tombstoned chunks."""
        ...


class Retriever(Protocol):
    """The query-side composition: text in, ranked chunks out.

    The vector retriever embeds the query and delegates to
    `VectorStore.search`. Future `HybridRetriever` and `GraphRetriever`
    implementations layer additional signal on top — but they all share
    this single async contract.
    """

    async def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]: ...
