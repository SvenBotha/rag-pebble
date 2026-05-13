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
    loader_for,
    walk_paths,
)
from pebble.core.interfaces import (
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
    ) -> None:
        self._chunker = chunker
        self._embedder = embedder
        self._store = store
        self._sources = sources
        self._limits = limits

    async def ingest_paths(
        self,
        paths: Iterable[Path] | None = None,
        *,
        on_progress: Callable[[Path, int, int], None] | None = None,
    ) -> IngestResult:
        """Ingest the documents under `paths` (defaults to sources from config).

        `on_progress`, when given, is called after each document is added
        with `(path_just_done, total_docs_so_far, total_chunks_so_far)`.
        """
        roots = list(paths) if paths is not None else list(self._sources.paths)
        ingested_documents = 0
        ingested_chunks = 0
        skipped = 0

        for path in walk_paths(roots, self._sources.include, self._sources.exclude):
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

                start_id = self._store.allocate_chunk_ids(len(chunks))
                chunks = [
                    replace(chunk, chunk_id=start_id + offset)
                    for offset, chunk in enumerate(chunks)
                ]
                vectors = await self._embedder.embed([c.text for c in chunks])
                self._store.add(chunks, vectors)

                ingested_documents += 1
                ingested_chunks += len(chunks)
                if on_progress is not None:
                    on_progress(path, ingested_documents, ingested_chunks)

        if ingested_chunks > 0:
            self._store.persist()
        return IngestResult(
            ingested_documents=ingested_documents,
            ingested_chunks=ingested_chunks,
            skipped=skipped,
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
