"""Pydantic config schema for Pebble.

Every field has a default so partial configs work. The loader
(`pebble.config.loader.load_config`) also validates that the env vars
required by the chosen providers are present — that check lives there
because env-var resolution is not a property of the schema itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Provider = Literal["openai"]
RetrievalMode = Literal["vector", "hybrid", "graph"]
ChunkingMethod = Literal["recursive"]


class SourcesConfig(BaseModel):
    paths: list[Path] = Field(default_factory=lambda: [Path("./docs")])
    include: list[str] = Field(default_factory=lambda: ["*.md", "*.txt", "*.pdf"])
    exclude: list[str] = Field(
        default_factory=lambda: ["**/node_modules/**", "**/.git/**"]
    )


class ChunkingConfig(BaseModel):
    method: ChunkingMethod = "recursive"
    chunk_size: int = Field(default=800, gt=0)
    overlap: int = Field(default=100, ge=0)


class EmbeddingsConfig(BaseModel):
    provider: Provider = "openai"
    model: str = "text-embedding-3-small"
    batch_size: int = Field(default=64, gt=0)


class LLMConfig(BaseModel):
    provider: Provider = "openai"
    model: str = "gpt-4o-mini"
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=800, gt=0)


class RetrievalConfig(BaseModel):
    mode: RetrievalMode = "vector"
    top_k: int = Field(default=5, gt=0)
    similarity_threshold: float = 0.0


class StorageConfig(BaseModel):
    index_path: Path = Path("./data/pebble.index")
    metadata_path: Path = Path("./data/pebble.meta.sqlite")


class LimitsConfig(BaseModel):
    max_document_mb: int = Field(default=25, gt=0)
    max_chunks_per_doc: int = Field(default=5000, gt=0)
    concurrency: int = Field(default=4, gt=0)
    max_tokens_per_query: int = Field(default=4000, gt=0)
    max_embeddings_per_ingest: int = Field(default=50000, gt=0)


class DebugConfig(BaseModel):
    show_chunks: bool = False
    show_scores: bool = False
    log_prompts: bool = False


class PebbleConfig(BaseModel):
    """Root configuration object. All sections optional."""

    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)

    model_config = {"extra": "forbid"}
