"""Retrievers: query string in, ranked chunks out."""

from __future__ import annotations

from pebble.core.interfaces import Embedder, RetrievedChunk, VectorStore


class VectorRetriever:
    """Embed the query, do a single FAISS search, return the hits."""

    def __init__(self, embedder: Embedder, store: VectorStore) -> None:
        self._embedder = embedder
        self._store = store

    async def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        vectors = await self._embedder.embed([query])
        if not vectors:
            return []
        return self._store.search(vectors[0], top_k)


class HybridRetriever:
    """Future: vector + lexical (BM25) fusion. Not implemented in v1."""

    async def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        raise NotImplementedError("hybrid retrieval is not implemented in v1")


class GraphRetriever:
    """Future: graph-augmented retrieval. Not implemented in v1."""

    async def retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        raise NotImplementedError("graph retrieval is not implemented in v1")
