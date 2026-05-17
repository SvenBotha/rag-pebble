"""Pydantic request and response models for the HTTP API.

These types are the only thing the API layer exposes outside the
process. The MCP adapter (future) will reuse them as tool input/output
schemas without modification.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, gt=0)
    debug: bool = False


class ChunkOut(BaseModel):
    text: str
    source_path: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    chunks: list[ChunkOut] = []


class IngestRequest(BaseModel):
    paths: list[str] | None = None


class IngestResponse(BaseModel):
    ingested_documents: int
    ingested_chunks: int
    skipped: int
    already_ingested: int = 0


class DeleteResponse(BaseModel):
    deleted_chunks: int


class CompactResponse(BaseModel):
    before: int
    after: int
    elapsed_seconds: float


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float


class ReadyResponse(BaseModel):
    ready: bool
    index_size: int | None = None
    reason: str | None = None


class PodOut(BaseModel):
    name: str
    chunk_count: int
    size_mb: float
    active: bool


class CreatePodRequest(BaseModel):
    name: str


class CreatePodResponse(BaseModel):
    name: str
    created: bool


class ActivatePodResponse(BaseModel):
    message: str


class DocumentInfoOut(BaseModel):
    doc_id: str
    source_path: str
    chunk_count: int
    created_at: str


class DocumentsResponse(BaseModel):
    documents: list[DocumentInfoOut]
    total: int


class ConfigResponse(BaseModel):
    config: dict[str, object]


class ReloadResponse(BaseModel):
    reloaded: bool
