# pebble/api/ — Agent Context

FastAPI surface. Routes are thin translators: parse request → call pipeline → wrap response. No business logic lives here.

## Files

| File | Purpose |
|------|---------|
| `app.py` | App factory + lifespan. Loads index in background; `/ready` 503 until done. JSON logging. Error handlers. |
| `routes.py` | All endpoints. Import `require_services` from `deps.py` for DI. |
| `models.py` | Pydantic request/response models. |
| `deps.py` | `require_services(request) → Services`. Returns 503 if services not yet loaded. |

## Error → HTTP status mapping (in `app.py`)

| Exception | Status |
|-----------|--------|
| `BudgetExceededError` | 402 |
| `ProviderAuthError` | 502 |
| `ProviderRateLimitError` | 503 |
| `ProviderTimeoutError` | 504 |
| `ProviderError` | 502 |
| `ConfigError` | 500 |
| `StoreError` | 500 |
| `PebbleError` | 500 |

When adding a new exception type, add a handler in `_install_error_handlers` in `app.py`.

## Current endpoints

```
POST /query             → QueryResponse
POST /ingest            → IngestResponse
DELETE /documents/{id}  → DeleteResponse
POST /admin/compact     → CompactResponse
GET  /health[?deep]     → HealthResponse
GET  /ready             → ReadyResponse (200 or 503)
```

## Endpoints to add (in priority order)

### 1. `GET /documents`
List all ingested documents with chunk counts. Query SQLite directly via `services.store`.

```python
# models.py
class DocumentInfo(BaseModel):
    doc_id: str
    source_path: str
    chunk_count: int
    created_at: str

class DocumentsResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int
```

The store needs a new method `list_documents() -> list[DocumentInfo]` (add to `VectorStore` Protocol and `FaissSqliteStore`).

### 2. `GET /pods` + `POST /pods` + `DELETE /pods/{name}` + `POST /pods/{name}/activate`

Use helpers from `pebble/core/pods.py`. The activate endpoint returns 202 with a message that the server must be restarted; it writes to config.yaml but does not hot-reload the FAISS index.

### 3. `GET /config` + `POST /config`

Read/write `config.yaml`. Use `pebble/config/loader.py` to load; use `pydantic` + `yaml.dump` to write.

### 4. `POST /admin/reload`

Re-call `build_services(load_config())` and replace `app.state.services`. Must acquire a lock to avoid serving stale state mid-swap.

### 5. `GET /ingest/stream` (SSE)

```python
from fastapi.responses import StreamingResponse

@router.get("/ingest/stream")
async def ingest_stream(services: Services = Depends(require_services)):
    async def generate():
        # drain an asyncio.Queue that IngestPipeline writes to via on_progress
        ...
    return StreamingResponse(generate(), media_type="text/event-stream")
```

Wire `on_progress` in `IngestPipeline` to write JSON events to a `asyncio.Queue` stored on `app.state`. The SSE endpoint drains this queue. Only one active ingest at a time (raise 409 if one is already running).

## Adding a new endpoint — checklist

1. Add Pydantic models to `models.py`
2. Add route function to `routes.py` with `Depends(require_services)`
3. If the route raises a new exception type, add a handler in `app.py`
4. Add a test in `tests/test_api.py` using `TestClient` with injected stub services
