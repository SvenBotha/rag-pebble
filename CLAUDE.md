# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                   # install deps (Python 3.12, managed by uv)
make run                  # start API server on :8000 (hot-reload: make dev)
make test                 # pytest (35 tests, fully offline — no API key needed)
make lint                 # ruff check pebble tests
make typecheck            # mypy pebble (strict)
make all                  # lint + typecheck + test

uv run pytest tests/test_retrieval.py          # run one test file
uv run pytest -k test_compact                  # run tests matching a pattern
uv run pytest -x -v                            # stop on first failure, verbose

make docker-build         # build pebble:latest
make docker-run           # run container (reads creds from .env, mounts ./data and ./config.yaml)
```

`OPENAI_API_KEY` must be set (or in `.env`) to run the server or CLI. Tests do not need it.

## Architecture

Pebble is a retrieval-only system: FAISS + SQLite run locally; all embedding and generation goes to cloud providers.

### The two callers of core

**Queries** (`pebble ask`, `pebble chat`) → HTTP → FastAPI → `QueryPipeline`

**Admin commands** (`pebble ingest`, `pebble delete`, `pebble compact`) → core directly via `asyncio.run`. This is intentional — first-time ingest works without a running server.

### The single wiring point

`pebble/bootstrap.py:build_services(config)` is the only place where concrete implementations are chosen and wired together. The API lifespan calls it via `asyncio.to_thread` (so index loading doesn't block the event loop). The CLI calls it directly.

### Protocol boundaries

`pebble/core/interfaces.py` defines the only shared surface. Key rule: **async on I/O-bound only** — `Embedder`, `LLMProvider`, `Retriever` are async; `Chunker`, `DocumentLoader`, `VectorStore` are sync (local disk/CPU).

### Ingestion pipeline

Chunks accumulate in a `pending` list across multiple documents until `embed_batch_size` (default 64) is reached, then embedded in one API call. This is ~10× fewer network calls than one-call-per-doc. `IngestPipeline.ingest_paths` is idempotent — it checks `store.has_document(doc_id)` before processing each file and skips docs already in the store.

### Storage

`FaissSqliteStore` (`pebble/core/store.py`) wraps FAISS `IndexIDMap2` (supports per-vector IDs + reconstruction for compaction) over `IndexFlatIP`, plus a SQLite table for chunk metadata.

- **Deletes are soft**: tombstone flag in SQLite; FAISS is never touched until `compact()`.
- **ID allocation** uses a single atomic `UPDATE id_sequence SET next_id = next_id + n RETURNING next_id - n` — safe for concurrent processes.
- **Compaction** rebuilds FAISS from live SQLite rows, then purges tombstones. Manual only — no automatic compaction.
- A `threading.RLock` serialises all store operations.

### Startup behaviour

`/health` returns 200 immediately. `/ready` returns 503 while the index loads in a background `asyncio.create_task`, then flips to 200. This lets orchestrators distinguish liveness from readiness.

### Error → HTTP status mapping

`BudgetExceededError` → 402, `ProviderAuthError` → 502, `ProviderRateLimitError` → 503, `ProviderTimeoutError` → 504, other `ProviderError` → 502, `ConfigError`/`StoreError` → 500. All handled in `pebble/api/app.py:_install_error_handlers`.

### Cost guards

`pebble/core/budgets.py` enforces `max_tokens_per_query` and `max_embeddings_per_ingest` from config **before** any network call. Uses a `chars/4` token estimator (conservative by design).

## Key config knobs (`examples/config.yaml`)

- `retrieval.similarity_threshold`: defaults to `0.0` (no filtering) — raising this is usually the quickest retrieval quality win.
- `limits.max_tokens_per_query` / `limits.max_embeddings_per_ingest`: cost guards, enforced in code before API calls.
- `embeddings.batch_size`: controls cross-doc batching in the ingest pipeline.
- `storage.index_path` / `storage.metadata_path`: where FAISS and SQLite live (mount as a volume in Docker).

## Memory limits

`IndexFlatIP` holds all vectors in RAM: `n_chunks × dim × 4 bytes`. At 1536 dims, the §8 target of 50k chunks requires ~307 MB for vectors + ~71 MB process overhead = ~378 MB total. Beyond ~80k chunks, switch to `IndexHNSWFlat` in `store.py`.

Ingest-time RSS is significantly higher than load-only RSS (~200 MB extra from the async HTTP heap). Run ingest offline; the serving process only loads a pre-built index.

## Load testing

```bash
make bench-sync                             # one-time: install datasets dep
make bench-prepare ARGS="--count 1000"      # write ./data/corpus/*.md (no API key)
make bench-run ARGS="--queries 100"         # embed + query, reports RSS vs 400 MB target
```

Only run one bench process at a time — concurrent processes share the same SQLite and will produce duplicate chunks even with the atomic ID allocator.

## `.env` file

`pebble/config/loader.py` calls `load_dotenv()` on every `load_config()` call. `bench/run_load_test.py` also calls it explicitly. Put `OPENAI_API_KEY=sk-...` in `.env` and it is picked up everywhere, including `make docker-run` (via `--env-file .env`).
