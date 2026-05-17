# Pebble — Agent Context

This file is the primary reference for AI agents (Cursor, Claude Code, etc.) working in this repository. Read it fully before making changes.

---

## What Pebble Is

A small, API-first RAG system designed to run on a 1–2 GB VPS. Pebble does retrieval locally (FAISS + SQLite) and delegates reasoning to cloud LLMs. One container, one config file, no managed services.

**The boundary that must never be crossed:** no local LLM inference, no Postgres, no Redis, no Kubernetes, no message brokers. Cloud providers for embeddings and generation only.

---

## What Has Been Built (Phases 0–3 + Phase A Pods, Complete)

### Core package (`pebble/`)
All production code is complete, tested, and passing mypy strict + ruff.

- **`pebble/core/interfaces.py`** — Protocol definitions and frozen dataclasses. The only shared surface between all subsystems. Do not add methods here without a concrete caller that needs them.
- **`pebble/core/pipeline.py`** — `IngestPipeline` and `QueryPipeline`. Ingest batches chunks across documents (up to `embed_batch_size`) before each embed call, cutting API calls ~10×. Ingest is idempotent: `has_document(doc_id)` is checked before processing each file.
- **`pebble/core/store.py`** — `FaissSqliteStore`. FAISS `IndexIDMap2` over `IndexFlatIP` + SQLite. Soft deletes (tombstone flag). Compaction is manual-only. ID allocation uses a single atomic `UPDATE ... RETURNING` — safe for concurrent processes.
- **`pebble/core/embeddings.py`** — `OpenAIEmbedder`. Async httpx. Enforces `max_embeddings_per_ingest` before the network call.
- **`pebble/core/llm.py`** — `OpenAILLM`. Async httpx. Enforces `max_tokens_per_query` before the network call.
- **`pebble/core/_http.py`** — Shared retry + error mapping (tenacity, exponential-backoff-with-jitter, typed exceptions).
- **`pebble/core/retrieval.py`** — `VectorRetriever` (live), `HybridRetriever`/`GraphRetriever` (NotImplementedError stubs).
- **`pebble/core/prompts.py`** — Single locked prompt template. Do not duplicate.
- **`pebble/core/budgets.py`** — Cost guards. chars/4 token estimate, conservative by design.
- **`pebble/core/ingestion.py`** — Loaders (txt/md/pdf), path walker, glob honouring, `doc_id_for(path)`.
- **`pebble/core/chunking.py`** — `RecursiveCharacterChunker`. Paragraph-aware breaks.
- **`pebble/core/errors.py`** — Exception taxonomy. All provider errors map to typed subclasses.
- **`pebble/core/pods.py`** — Pod management helpers: `PodInfo`, `list_pods`, `create_pod`, `delete_pod`, `write_active_pod`. Pure-sync, no store/bootstrap dependency. Name validation rejects path traversal (`^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$`).
- **`pebble/bootstrap.py`** — `build_services(config) → Services`. The only wiring point. Both the API lifespan and CLI call this. Uses `config.storage.resolved_index_path` / `config.storage.resolved_metadata_path`.
- **`pebble/config/schema.py`** — Pydantic models for the full config. `StorageConfig` now has `pods_dir` + `active_pod` with `resolved_index_path` / `resolved_metadata_path` computed properties. Old `index_path` / `metadata_path` fields remain as deprecated optional fallbacks (when set they take precedence over pod resolution, preserving backward compat).
- **`pebble/config/loader.py`** — YAML loading, `load_dotenv()`, env-var validation per provider.
- **`pebble/api/app.py`** — FastAPI app factory with async lifespan. `/health` 200 from boot; `/ready` 503 until index loads. Stores the resolved `config_path` in `app.state.config_path` for use by the activate endpoint.
- **`pebble/api/routes.py`** — 10 endpoints: POST /query, POST /ingest, DELETE /documents/{doc_id}, POST /admin/compact, GET /health, GET /ready, GET /pods, POST /pods, DELETE /pods/{name}, POST /pods/{name}/activate.
- **`pebble/api/models.py`** — Pydantic request/response models, including `PodOut`, `CreatePodRequest`, `CreatePodResponse`, `ActivatePodResponse`.
- **`pebble/api/deps.py`** — DI providers.
- **`pebble/cli/main.py`** — Typer CLI. Admin commands call core directly via `asyncio.run`. Query commands hit the HTTP API. `pebble pods` subcommand group: `list`, `create`, `delete`, `switch`. `--pod` flag on `ingest`, `delete`, `compact` overrides `active_pod` for that invocation.

### Pods behaviour summary

- Each pod is an independent FAISS index + SQLite under `data/pods/<name>/`.
- Default pod is `"default"`. Config: `storage.pods_dir` + `storage.active_pod`.
- `DELETE /pods/{name}` refuses (409) if the target is the active pod.
- `POST /pods/{name}/activate` writes `active_pod` to `config.yaml` on disk and returns 202 — the server must be restarted for the switch to take effect.
- `--pod` on query commands (`ask`, `chat`) is deferred to Phase B; the running server is locked to one pod at startup.

### Tests (`tests/`)
56 tests, fully offline (no API key needed). Stubs in `tests/conftest.py`: `StubEmbedder` (deterministic hash vectors), `StubLLM` (canned responses). `tests/test_pods.py` covers pod CRUD, name validation, API endpoints, `write_active_pod`, and backward compat.

### Bench (`bench/`)
`prepare_corpus.py` streams from HuggingFace Wikipedia. `run_load_test.py` ingests, runs concurrent queries (Semaphore(5)), reports RSS vs 400 MB target.

### Deployment
- `Dockerfile` — multi-stage, `python:3.12-slim` base, uv for install
- `make docker-build` + `make docker-run` (uses `--env-file .env`)
- `pyproject.toml` — uv-managed, hatchling build, ruff/mypy/pytest configured

---

## What Needs to Be Built Next

---

## Feature 2: TUI (Terminal User Interface)

### Library
`textual >= 0.60` — async-native, component-based. Add to `pyproject.toml` `dependencies`.

### Location
`pebble/tui/` — see `pebble/tui/agents.md` for detailed file-by-file breakdown.

### New CLI command
```python
# pebble/cli/main.py
@app.command()
def tui(api_url: str | None = typer.Option(None, "--api-url")) -> None:
    """Launch the interactive TUI."""
    from pebble.tui.app import PebbleApp
    PebbleApp(api_url=_api_url(api_url)).run()
```

### Screens

#### Chat (default screen)
- Scrollable message history: user queries + assistant answers
- Inline citations rendered from `source_path` fields
- `--debug` toggle: expands each answer to show retrieved chunks + scores
- Status bar: active pod name, chunk count, model name
- Input box at bottom

#### Documents
- Scrollable table: `source_path`, chunk count, ingested date
- Per-row actions: Delete (soft-delete via `DELETE /documents/{doc_id}`), Re-ingest (force re-embed)
- Toolbar: Ingest new path (opens path input), Compact (calls `POST /admin/compact`)
- Live progress bar during ingest fed by SSE stream (see below)

#### Pods
- List all pods from `GET /pods` with chunk count, size, active indicator
- Actions: Create pod (name input), Delete pod (confirm), Switch pod (calls `POST /pods/{name}/activate`)
- New pod ingestion: select pod → ingest paths into it

#### Config Editor
- Form-based, grouped by config section
- Fields: text inputs, number spinners, dropdowns for provider/mode
- Save button: writes to `config.yaml` via `POST /config`, then calls `POST /admin/reload`
- Change detection: highlight fields that require re-ingest when changed:
  - **Requires re-ingest:** `embeddings.model`, `chunking.chunk_size`, `chunking.overlap`
  - **Requires restart:** `storage.active_pod`
  - **Live:** `llm.model`, `retrieval.top_k`, `similarity_threshold`, `limits.*`

#### Status Sidebar (persistent, all screens)
- Active pod name + chunk count
- `/health` uptime
- `/ready` state (polling every 5s)
- Last ingest timestamp

### New API endpoints needed for TUI

```
GET  /documents                # list ingested docs: {doc_id, source_path, chunk_count, created_at}
GET  /config                   # read current config.yaml as JSON
POST /config                   # write config changes (body: partial PebbleConfig)
POST /admin/reload             # re-read config from disk without full restart
GET  /ingest/stream            # SSE: streams IngestProgress events during active ingest
```

### SSE ingest progress
`GET /ingest/stream` returns `text/event-stream`. Events:
```json
{"type": "progress", "docs": 42, "chunks": 187, "elapsed_s": 12.3}
{"type": "complete", "ingested_documents": 1000, "ingested_chunks": 5570, "skipped": 0}
{"type": "error", "message": "..."}
```

The `IngestPipeline.ingest_paths` already has `on_progress` callback — wire it to an `asyncio.Queue` that the SSE endpoint drains.

---

## Build Order

### Phase A — Pods backend ✓ COMPLETE
All items done. See "Pods behaviour summary" above.

### Phase B — TUI backend prerequisites
1. `GET /documents` endpoint
2. `GET /config` + `POST /config` + `POST /admin/reload`
3. SSE ingest progress (`GET /ingest/stream`)
4. Tests for all new endpoints

### Phase C — TUI build
5. Add `textual >= 0.60` to `pyproject.toml`
6. `pebble/tui/app.py` — Textual App skeleton with tab navigation
7. Chat screen wired to `POST /query`
8. Status sidebar wired to `/health` + `/ready`
9. Documents screen wired to `GET /documents` + delete + compact
10. Ingest panel with SSE progress bar
11. Pods screen wired to `/pods` endpoints
12. Config editor form wired to `GET /config` + `POST /config`
13. `pebble tui` CLI command
14. TUI integration tests (Textual's `App.run_test()`)

---

## Architectural Rules (Do Not Violate)

1. `pebble/core/interfaces.py` is the only shared surface. Add methods only when a concrete caller requires them.
2. Async on exactly: `Embedder`, `LLMProvider`, `Retriever`. Everything else sync.
3. `build_services(config)` in `bootstrap.py` is the only wiring point. No globals, no module-level singletons.
4. Budget checks fire **before** network calls. Never skip them.
5. No automatic FAISS compaction. Manual only.
6. All HTTP calls use the shared retry logic in `pebble/core/_http.py`.
7. Typed exceptions from `pebble/core/errors.py`. Never raise bare `Exception` across a module boundary.
8. The store's `allocate_chunk_ids` uses atomic `UPDATE ... RETURNING` — do not replace with a read-then-write pattern.
9. `pebble/core/prompts.py` contains the one locked prompt template. Do not create alternatives inline.
10. The TUI calls the HTTP API for all operations. It does not import `pebble.core` directly (unlike the CLI admin commands, which pre-date the TUI).

---

## Running the Project

```bash
uv sync                        # install deps
cp examples/config.yaml .      # or create your own
# add OPENAI_API_KEY=sk-... to .env
make run                       # API server on :8000
uv run pebble ingest ./docs    # ingest (no server needed)
uv run pebble ask "..."        # query (server must be running)
make test                      # 56 offline tests
make docker-build && make docker-run
```
