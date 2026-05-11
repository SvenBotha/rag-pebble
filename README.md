# Pebble

A small, API-first RAG system designed to run on a 1–2 GB VPS.

Pebble does retrieval locally (FAISS + SQLite) and delegates reasoning to cloud
LLMs. One container, one config file, no managed services. The target footprint
is under 400 MB resident memory with a 50k-chunk index loaded.

## Status

Scaffolded. Phase 0 (vertical slice) and Phases 1–2 (interfaces + full
implementation) are complete. Phase 3 (load-test hardening) is pending.

## Quickstart

```bash
# 1. Install uv (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install dependencies
uv sync

# 3. Set your API key
export OPENAI_API_KEY=sk-...

# 4. Copy the example config (or point pebble at examples/config.yaml directly)
cp examples/config.yaml ./config.yaml

# 5. Ingest some documents (calls core directly — no server needed)
uv run pebble ingest examples/docs

# 6. Start the API
make run                            # or: uv run uvicorn pebble.api.app:app

# 7. Ask questions (in another shell)
uv run pebble ask "How long do I have to return an unopened product?"
uv run pebble ask "Do you ship to PO boxes?" --debug
```

## CLI

| Command                  | Path        | Description                                |
| ------------------------ | ----------- | ------------------------------------------ |
| `pebble ingest [PATH]`   | core direct | Ingest documents. Works without server.    |
| `pebble ask "..."`       | HTTP        | Ask one question against the running API.  |
| `pebble chat`            | HTTP        | REPL loop hitting the API.                 |
| `pebble delete <doc_id>` | core direct | Soft-delete all chunks for a document.     |
| `pebble compact`         | core direct | Rebuild the FAISS index from live rows.    |

The CLI is sync at the edge. Admin commands invoke the core directly via
`asyncio.run` so first-time ingest works without a server.

## API

| Method | Path                       | Body / Result                                    |
| ------ | -------------------------- | ------------------------------------------------ |
| POST   | `/query`                   | `{query, top_k?, debug?}` → `{answer, chunks?}`  |
| POST   | `/ingest`                  | `{paths?}` → `{ingested_documents, ingested_chunks, skipped}` |
| DELETE | `/documents/{doc_id}`      | → `{deleted_chunks}`                             |
| POST   | `/admin/compact`           | → `{before, after, elapsed_seconds}`             |
| GET    | `/health[?deep=true]`      | → `{status, uptime_seconds, ...}`                |
| GET    | `/ready`                   | 200 if index loaded, else 503                    |

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the design — query trace, locked
decisions, module map, and MCP forward-compatibility notes.

For the simplest end-to-end reference, read
[`scripts/vertical_slice.py`](scripts/vertical_slice.py) — the ~200-line
single-file pipeline that proves the whole system works.

## Tests

```bash
uv run pytest          # 30 tests, fully offline; no API keys required
uv run ruff check .    # lint
uv run mypy pebble     # type-check (strict)
make all               # all three
```

## Docker

```bash
make docker-build
make docker-run                    # mounts ./data and ./config.yaml
```

Image base: `python:3.12-slim`. No build tools in the final layer.

## License

MIT. See `pyproject.toml`.
