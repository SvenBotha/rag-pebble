"""HTTP endpoints.

Each route is a thin translator: parse pydantic input → call pipeline
method → wrap the result in a pydantic response. No business logic
lives here.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from pebble.api.deps import require_services
from pebble.api.models import (
    ActivatePodResponse,
    ChunkOut,
    CompactResponse,
    ConfigResponse,
    CreatePodRequest,
    CreatePodResponse,
    DeleteResponse,
    DocumentInfoOut,
    DocumentsResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    PodOut,
    QueryRequest,
    QueryResponse,
    ReadyResponse,
    ReloadResponse,
)
from pebble.bootstrap import Services, build_services
from pebble.config.loader import load_config
from pebble.config.schema import PebbleConfig
from pebble.core.errors import ConfigError, StoreError
from pebble.core.pods import create_pod, delete_pod, list_pods, write_active_pod

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
    request: Request,
    services: Services = Depends(require_services),
) -> IngestResponse:
    if getattr(request.app.state, "ingest_active", False):
        raise HTTPException(status_code=409, detail="ingest already in progress")

    request.app.state.ingest_active = True
    start = time.time()

    def on_progress(path: Path, docs: int, chunks: int) -> None:
        q: asyncio.Queue[dict[str, Any]] | None = getattr(
            request.app.state, "ingest_queue", None
        )
        if q is not None:
            q.put_nowait(
                {
                    "type": "progress",
                    "docs": docs,
                    "chunks": chunks,
                    "elapsed_s": round(time.time() - start, 1),
                }
            )

    paths = [Path(p) for p in body.paths] if body.paths else None
    try:
        result = await services.ingest.ingest_paths(paths, on_progress=on_progress)
        q = getattr(request.app.state, "ingest_queue", None)
        if q is not None:
            q.put_nowait(
                {
                    "type": "complete",
                    "ingested_documents": result.ingested_documents,
                    "ingested_chunks": result.ingested_chunks,
                    "skipped": result.skipped,
                }
            )
    except Exception as exc:
        q = getattr(request.app.state, "ingest_queue", None)
        if q is not None:
            q.put_nowait({"type": "error", "message": str(exc)})
        raise
    finally:
        request.app.state.ingest_active = False

    return IngestResponse(
        ingested_documents=result.ingested_documents,
        ingested_chunks=result.ingested_chunks,
        skipped=result.skipped,
        already_ingested=result.already_ingested,
    )


@router.get("/ingest/stream")
async def ingest_stream(request: Request) -> StreamingResponse:
    """SSE stream of ingest progress events.

    The endpoint creates the queue and stores it on app.state so that the
    POST /ingest handler can write events into it. Connect before triggering
    POST /ingest to capture all events.
    """
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    request.app.state.ingest_queue = queue

    async def generate() -> Any:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=300.0)
            except TimeoutError:
                yield f"data: {json.dumps({'type': 'error', 'message': 'stream timeout'})}\n\n"
                return
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] in ("complete", "error"):
                request.app.state.ingest_queue = None
                return

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/documents", response_model=DocumentsResponse)
async def list_documents(
    services: Services = Depends(require_services),
) -> DocumentsResponse:
    docs = services.store.list_documents()
    return DocumentsResponse(
        documents=[
            DocumentInfoOut(
                doc_id=d.doc_id,
                source_path=d.source_path,
                chunk_count=d.chunk_count,
                created_at=d.created_at,
            )
            for d in docs
        ],
        total=len(docs),
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


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@router.get("/config", response_model=ConfigResponse)
async def get_config(
    services: Services = Depends(require_services),
) -> ConfigResponse:
    return ConfigResponse(config=services.config.model_dump(mode="json"))


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `overlay` into a copy of `base`."""
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@router.post("/config", response_model=ConfigResponse)
async def save_config(
    body: dict[str, Any],
    request: Request,
    services: Services = Depends(require_services),
) -> ConfigResponse:
    config_path: Path | None = getattr(request.app.state, "config_path", None)

    existing: dict[str, Any] = services.config.model_dump(mode="json")
    merged = _deep_merge(existing, body)

    try:
        validated = PebbleConfig.model_validate(merged)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    write_path = config_path if config_path is not None else Path.cwd() / "config.yaml"
    try:
        write_path.write_text(yaml.dump(merged, default_flow_style=False), encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"failed to write config: {exc}") from exc

    if config_path is None:
        request.app.state.config_path = write_path

    return ConfigResponse(config=validated.model_dump(mode="json"))


@router.post("/admin/reload", response_model=ReloadResponse)
async def reload_config(
    request: Request,
    services: Services = Depends(require_services),
) -> ReloadResponse:
    config_path: Path | None = getattr(request.app.state, "config_path", None)
    config = load_config(config_path)
    new_services = await asyncio.to_thread(build_services, config)
    old_services = request.app.state.services
    request.app.state.services = new_services
    await old_services.aclose()
    return ReloadResponse(reloaded=True)


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


# ---------------------------------------------------------------------------
# Pods
# ---------------------------------------------------------------------------


@router.get("/pods", response_model=list[PodOut])
async def list_pods_route(
    services: Services = Depends(require_services),
) -> list[PodOut]:
    pods = list_pods(
        pods_dir=services.config.storage.pods_dir,
        active_pod=services.config.storage.active_pod,
    )
    return [
        PodOut(name=p.name, chunk_count=p.chunk_count, size_mb=p.size_mb, active=p.active)
        for p in pods
    ]


@router.post("/pods", response_model=CreatePodResponse, status_code=201)
async def create_pod_route(
    body: CreatePodRequest,
    services: Services = Depends(require_services),
) -> CreatePodResponse:
    try:
        create_pod(pods_dir=services.config.storage.pods_dir, name=body.name)
    except StoreError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CreatePodResponse(name=body.name, created=True)


@router.delete("/pods/{name}", response_model=DeleteResponse)
async def delete_pod_route(
    name: str,
    services: Services = Depends(require_services),
) -> DeleteResponse:
    if name == services.config.storage.active_pod:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot delete the active pod {name!r}; switch to another pod first",
        )
    try:
        delete_pod(pods_dir=services.config.storage.pods_dir, name=name)
    except StoreError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DeleteResponse(deleted_chunks=0)


@router.post("/pods/{name}/activate", response_model=ActivatePodResponse, status_code=202)
async def activate_pod_route(
    name: str,
    request: Request,
    services: Services = Depends(require_services),
) -> ActivatePodResponse:
    pods_dir = services.config.storage.pods_dir
    pod_dir = pods_dir / name
    if not pod_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"pod {name!r} does not exist",
        )
    config_path: Path | None = getattr(request.app.state, "config_path", None)
    # Fall back to a live lookup in case config.yaml was created after server start.
    if config_path is None:
        candidate = Path.cwd() / "config.yaml"
        if candidate.is_file():
            config_path = candidate
            request.app.state.config_path = config_path
    write_active_pod(config_path, name)
    msg = f"active_pod set to {name!r}"
    if config_path is not None:
        msg += f"; restart the server for the change to take effect (config: {config_path})"
    else:
        msg += "; no config.yaml found on disk — set storage.active_pod manually and restart"
    return ActivatePodResponse(message=msg)
