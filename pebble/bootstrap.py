"""Wire config → concrete services.

Single function: `build_services(config)`. Returns a `Services` bundle
containing the wired pipelines and the underlying httpx client. The
API layer's lifespan and the CLI's direct-call entry points both go
through here. There is no other path to a concrete service graph.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from pebble.config.schema import PebbleConfig
from pebble.core.chunking import RecursiveCharacterChunker
from pebble.core.embeddings import OpenAIEmbedder
from pebble.core.errors import ConfigError
from pebble.core.interfaces import Embedder, LLMProvider, Retriever, VectorStore
from pebble.core.llm import OpenAILLM
from pebble.core.pipeline import IngestPipeline, QueryPipeline
from pebble.core.retrieval import VectorRetriever
from pebble.core.store import FaissSqliteStore


@dataclass
class Services:
    config: PebbleConfig
    http_client: httpx.AsyncClient
    embedder: Embedder
    llm: LLMProvider
    store: VectorStore
    retriever: Retriever
    ingest: IngestPipeline
    query: QueryPipeline

    async def aclose(self) -> None:
        await self.http_client.aclose()


def build_services(config: PebbleConfig) -> Services:
    """Synchronous service construction.

    The API lifespan calls this through `asyncio.to_thread` so that
    loading a large FAISS index does not block the event loop. The CLI
    calls it directly.
    """
    http_client = httpx.AsyncClient(
        limits=httpx.Limits(max_keepalive_connections=8, max_connections=16),
    )

    embedder = _build_embedder(config, http_client)
    llm = _build_llm(config, http_client)

    store = FaissSqliteStore(
        index_path=config.storage.resolved_index_path,
        metadata_path=config.storage.resolved_metadata_path,
        dim=embedder.dim,
    )
    store.load()

    chunker = RecursiveCharacterChunker(
        chunk_size=config.chunking.chunk_size,
        overlap=config.chunking.overlap,
    )

    retriever = _build_retriever(config, embedder, store)

    ingest = IngestPipeline(
        chunker=chunker,
        embedder=embedder,
        store=store,
        sources=config.sources,
        limits=config.limits,
        embed_batch_size=config.embeddings.batch_size,
    )
    query = QueryPipeline(
        retriever=retriever,
        llm=llm,
        store=store,
        llm_config=config.llm,
        retrieval_config=config.retrieval,
    )

    return Services(
        config=config,
        http_client=http_client,
        embedder=embedder,
        llm=llm,
        store=store,
        retriever=retriever,
        ingest=ingest,
        query=query,
    )


def _build_embedder(
    config: PebbleConfig, client: httpx.AsyncClient
) -> Embedder:
    if config.embeddings.provider == "openai":
        return OpenAIEmbedder(
            client=client,
            model=config.embeddings.model,
            batch_size=config.embeddings.batch_size,
            max_embeddings_per_ingest=config.limits.max_embeddings_per_ingest,
        )
    raise ConfigError(f"unsupported embeddings provider: {config.embeddings.provider!r}")


def _build_llm(config: PebbleConfig, client: httpx.AsyncClient) -> LLMProvider:
    if config.llm.provider == "openai":
        return OpenAILLM(
            client=client,
            model=config.llm.model,
            max_tokens_per_query=config.limits.max_tokens_per_query,
        )
    raise ConfigError(f"unsupported LLM provider: {config.llm.provider!r}")


def _build_retriever(
    config: PebbleConfig, embedder: Embedder, store: VectorStore
) -> Retriever:
    if config.retrieval.mode == "vector":
        return VectorRetriever(embedder=embedder, store=store)
    raise ConfigError(
        f"retrieval mode {config.retrieval.mode!r} is not implemented in v1; "
        "use 'vector'"
    )
