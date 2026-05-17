"""The two composed flows: ingest and query.

Pipelines are concrete classes (not Protocols). They glue together the
Protocol-typed dependencies that bootstrap supplies. Everything
domain-specific that doesn't belong in a single subsystem lives here:
budget checks on chunk counts, per-document atomic ID allocation,
similarity-threshold filtering, prompt assembly.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from pebble.config.schema import (
    LimitsConfig,
    LLMConfig,
    RetrievalConfig,
    SourcesConfig,
)
from pebble.core.errors import PebbleError
from pebble.core.ingestion import (
    UnsupportedFileType,
    doc_id_for,
    loader_for,
    walk_paths,
)
from pebble.core.interfaces import (
    Chunk,
    Chunker,
    Embedder,
    LLMProvider,
    RetrievedChunk,
    Retriever,
    VectorStore,
)
from pebble.core.prompts import SYSTEM_PROMPT, assemble_user_message


@dataclass(frozen=True, slots=True)
class IngestResult:
    ingested_documents: int
    ingested_chunks: int
    skipped: int
    already_ingested: int = 0


@dataclass(frozen=True, slots=True)
class QueryResult:
    answer: str
    chunks: list[RetrievedChunk]


@dataclass(frozen=True, slots=True)
class CompactResult:
    before: int
    after: int
    elapsed_seconds: float


class IngestPipeline:
    def __init__(
        self,
        chunker: Chunker,
        embedder: Embedder,
        store: VectorStore,
        sources: SourcesConfig,
        limits: LimitsConfig,
        embed_batch_size: int = 64,
    ) -> None:
        self._chunker = chunker
        self._embedder = embedder
        self._store = store
        self._sources = sources
        self._limits = limits
        self._embed_batch_size = embed_batch_size

    async def ingest_paths(
        self,
        paths: Iterable[Path] | None = None,
        *,
        on_progress: Callable[[Path, int, int], None] | None = None,
    ) -> IngestResult:
        """Ingest documents under `paths`, batching chunks across docs.

        Chunks from multiple documents are accumulated until `embed_batch_size`
        is reached, then embedded in a single API call. This cuts network
        round-trips by ~10× versus one call per document.

        `on_progress(path, docs_so_far, chunks_queued_or_done)` fires after
        each document's chunks are queued, before they may be flushed.
        """
        roots = list(paths) if paths is not None else list(self._sources.paths)
        ingested_documents = 0
        ingested_chunks = 0
        skipped = 0
        already_ingested = 0
        pending: list[Chunk] = []

        async def _flush_batch(batch: list[Chunk]) -> int:
            start_id = self._store.allocate_chunk_ids(len(batch))
            assigned = [
                replace(c, chunk_id=start_id + i) for i, c in enumerate(batch)
            ]
            vectors = await self._embedder.embed([c.text for c in assigned])
            self._store.add(assigned, vectors)
            return len(batch)

        for path in walk_paths(roots, self._sources.include, self._sources.exclude):
            if self._store.has_document(doc_id_for(path)):
                already_ingested += 1
                continue

            try:
                loader = loader_for(path)
            except UnsupportedFileType:
                skipped += 1
                continue

            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > self._limits.max_document_mb:
                skipped += 1
                continue

            for doc in loader.load(path):
                chunks = list(self._chunker.chunk(doc))
                if not chunks:
                    continue
                if len(chunks) > self._limits.max_chunks_per_doc:
                    skipped += 1
                    continue

                pending.extend(chunks)
                ingested_documents += 1
                if on_progress is not None:
                    on_progress(path, ingested_documents, ingested_chunks + len(pending))

                while len(pending) >= self._embed_batch_size:
                    ingested_chunks += await _flush_batch(
                        pending[: self._embed_batch_size]
                    )
                    del pending[: self._embed_batch_size]

        if pending:
            ingested_chunks += await _flush_batch(pending)

        if ingested_chunks > 0:
            self._store.persist()
        return IngestResult(
            ingested_documents=ingested_documents,
            ingested_chunks=ingested_chunks,
            skipped=skipped,
            already_ingested=already_ingested,
        )


class QueryPipeline:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMProvider,
        store: VectorStore,
        llm_config: LLMConfig,
        retrieval_config: RetrievalConfig,
    ) -> None:
        self._retriever = retriever
        self._llm = llm
        self._store = store
        self._llm_config = llm_config
        self._retrieval_config = retrieval_config

    async def ask(
        self,
        query: str,
        *,
        top_k: int | None = None,
    ) -> QueryResult:
        if not query.strip():
            raise PebbleError("query is empty")

        effective_top_k = top_k or self._retrieval_config.top_k
        hits = await self._retriever.retrieve(query, effective_top_k)

        threshold = self._retrieval_config.similarity_threshold
        if threshold > 0.0:
            hits = [h for h in hits if h.score >= threshold]

        if not hits:
            return QueryResult(
                answer="No relevant context was found to answer that question.",
                chunks=[],
            )

        user_message = assemble_user_message(query, hits)
        answer = await self._llm.complete(
            user_message,
            system=SYSTEM_PROMPT,
            temperature=self._llm_config.temperature,
            max_tokens=self._llm_config.max_tokens,
        )
        return QueryResult(answer=answer, chunks=hits)

    def delete_document(self, doc_id: str) -> int:
        return self._store.delete_document(doc_id)

    def compact(self) -> CompactResult:
        before = self._store.live_count
        start = time.monotonic()
        self._store.compact()
        elapsed = time.monotonic() - start
        return CompactResult(
            before=before,
            after=self._store.live_count,
            elapsed_seconds=elapsed,
        )
