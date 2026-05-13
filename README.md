# Pebble

A small, API-first RAG system designed to run on a 1–2 GB VPS.

Pebble does retrieval locally (FAISS + SQLite) and delegates reasoning to cloud
LLMs. One container, one config file, no managed services. The target footprint
is under 400 MB resident memory with a 50k-chunk index loaded.

## Status

Scaffolded. Phase 0 (vertical slice) and Phases 1–2 (interfaces + full
implementation) are complete. Phase 3 (load-test hardening) is pending; runnable
checks and corpus prep live under [`bench/`](bench/) — see **Bench / load testing** below.

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

## Tests

```bash
uv run pytest          # 30 tests, fully offline; no API keys required
uv run ruff check .    # lint
uv run mypy pebble     # type-check (strict)
make all               # all three
```

## Bench / load testing

Phase 3 tooling lives under [`bench/`](bench/). It ingests a Wikipedia-derived
corpus via the normal pipeline, runs repeated queries against OpenAI, and prints
RSS (resident set size) plus latency stats. **Requires `OPENAI_API_KEY` in the
environment** — same as the rest of the app. The project does not load `.env`
automatically; export the key in your shell (or use a tool that injects it).

```bash
# Install optional bench dependencies (HuggingFace `datasets`, etc.)
make bench-sync

# Build a local corpus (default: 1000 Simple English articles → ./data/corpus)
make bench-prepare

# Custom size / dataset variant (see bench/prepare_corpus.py --help)
make bench-prepare ARGS='--count 5000'
make bench-prepare ARGS='--variant 20231101.en --count 2000'

# Run load test: ingest corpus, run queries, report RSS vs 400 MB target
# Default corpus: ./data/corpus, default queries: 100
make bench-run

# Override paths and query count (see bench/run_load_test.py --help)
make bench-run ARGS='--corpus ./data/corpus --queries 50'
```

Equivalent without Make:

```bash
uv sync --group bench
uv run --group bench python bench/prepare_corpus.py --count 1000
uv run --group bench python bench/run_load_test.py --corpus ./data/corpus --queries 100
```

**Cost:** a large ingest plus many queries calls the embeddings and chat APIs
repeatedly. As a rule of thumb, the script docstring cites on the order of
**~$0.20–$0.25** for a heavy run (e.g. on the scale of ~50k chunks and 100
queries with default-style models); scale down `--count` and `--queries` for
cheaper smoke tests.

**Progress:** `run_load_test.py` prints little or no output during **ingest**
(it is embedding every chunk). Long pauses after “services built” usually mean
ingestion is still running, not a hang.

## Docker

```bash
make docker-build
make docker-run                    # mounts ./data and ./config.yaml
```

Image base: `python:3.12-slim`. No build tools in the final layer.

## License

MIT. See `pyproject.toml`.
