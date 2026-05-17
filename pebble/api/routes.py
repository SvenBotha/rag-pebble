"""HTTP endpoints.

Each route is a thin translator: parse pydantic input → call pipeline
method → wrap the result in a pydantic response. No business logic
lives here.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from pebble.api.deps import require_services
from pebble.api.models import (
    ChunkOut,
    CompactResponse,
    DeleteResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    ReadyResponse,
)
from pebble.bootstrap import Services

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    services: Services = Depends(require_services),
) -> QueryResponse:
    result = await services.query.ask(body.query, top_k=body.top_k)
    chunks_out = (
        [
            ChunkOut(
                text=h.chunk.text,
                source_path=h.chunk.source_path,
                score=h.score,
            )
            for h in result.chunks
        ]
        if body.debug
        else []
    )
    return QueryResponse(answer=result.answer, chunks=chunks_out)


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    body: IngestRequest,
    services: Services = Depends(require_services),
) -> IngestResponse:
    paths = [Path(p) for p in body.paths] if body.paths else None
    result = await services.ingest.ingest_paths(paths)
    return IngestResponse(
        ingested_documents=result.ingested_documents,
        ingested_chunks=result.ingested_chunks,
        skipped=result.skipped,
        already_ingested=result.already_ingested,
    )


@router.delete("/documents/{doc_id}", response_model=DeleteResponse)
async def delete_document(
    doc_id: str,
    services: Services = Depends(require_services),
) -> DeleteResponse:
    deleted = services.query.delete_document(doc_id)
    return DeleteResponse(deleted_chunks=deleted)


@router.post("/admin/compact", response_model=CompactResponse)
async def compact(
    services: Services = Depends(require_services),
) -> CompactResponse:
    result = services.query.compact()
    return CompactResponse(
        before=result.before,
        after=result.after,
        elapsed_seconds=result.elapsed_seconds,
    )


@router.get("/health", response_model=HealthResponse)
async def health(request: Request, deep: bool = False) -> JSONResponse:
    uptime = time.time() - request.app.state.start_time
    payload = {"status": "ok", "uptime_seconds": uptime}

    if not deep:
        return JSONResponse(payload)

    services: Services | None = getattr(request.app.state, "services", None)
    if services is None:
        return JSONResponse(
            {**payload, "status": "degraded", "reason": "services not ready"},
            status_code=503,
        )

    try:
        await services.embedder.embed(["ping"])
    except Exception as e:  # noqa: BLE001 — surface any provider error here
        return JSONResponse(
            {**payload, "status": "degraded", "embedder_error": str(e)},
            status_code=503,
        )
    try:
        await services.llm.complete(
            "Reply with the word OK.",
            system="Be terse.",
            temperature=0.0,
            max_tokens=4,
        )
    except Exception as e:  # noqa: BLE001 — surface any provider error here
        return JSONResponse(
            {**payload, "status": "degraded", "llm_error": str(e)},
            status_code=503,
        )

    return JSONResponse(payload)


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request) -> JSONResponse:
    ready_flag = bool(getattr(request.app.state, "ready", False))
    services: Services | None = getattr(request.app.state, "services", None)
    error = getattr(request.app.state, "ready_error", None)

    if ready_flag and services is not None:
        return JSONResponse(
            ReadyResponse(ready=True, index_size=services.store.live_count).model_dump()
        )

    reason = "loading_index" if error is None else f"startup_failed: {error}"
    return JSONResponse(
        ReadyResponse(ready=False, reason=reason).model_dump(),
        status_code=503,
    )
