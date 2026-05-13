# Pebble — Architecture

A small RAG backend designed for a 1–2 GB VPS. The system does retrieval
locally and delegates reasoning to cloud LLMs. Every design choice here
defends that boundary.

If something on this page contradicts a clever idea you're about to add,
the page wins. Open a PR to change it first.

---

## 1. Shape

```
CLI (typer)                        HTTP clients
    │                                    │
    │ admin commands                     │ queries
    │ (ingest, delete, compact)          │
    │ call core directly                 │
    │                                    ▼
    │                              FastAPI app
    │                                    │
    └─────────────► Core pipeline ◄──────┘
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
   Ingestion        Retrieval          Generation
   loader+chunker   embedder+store     llm provider
                          │
                          ▼
                  FAISS  +  SQLite
                  (vectors) (metadata + tombstones)
```

The CLI talks to two destinations:

- **Queries** (`pebble ask`, `pebble chat`) → HTTP → FastAPI.
- **Admin** (`pebble ingest`, `pebble delete`, `pebble compact`) → core
  directly, via `asyncio.run`. This is a deliberate exception so first
  ingestion works without a running server. It is not hidden; it is
  exactly the same code the API calls.

---

## 2. Tracing a query

A call to `pebble ask "How long do I have to return an item?"`:

1. `pebble/cli/main.py` parses args, sends `POST /query` with
   `{"query": "...", "debug": false}` to the API URL (default
   `http://localhost:8000`).
2. `pebble/api/routes.py:query` deserialises into `QueryRequest`,
   pulls the `Retriever` and `LLMProvider` from DI.
3. `Retriever.retrieve(query, top_k)`:
   - `Embedder.embed([query])` → one vector (async HTTP).
   - `VectorStore.search(vector, top_k)` → list of `RetrievedChunk`
     (sync, FAISS in-memory + SQLite tombstone filter).
4. `pebble/core/prompts.py:assemble_user_message` builds the context
   block from the retrieved chunks in descending-score order.
5. `LLMProvider.complete(prompt, system=SYSTEM_PROMPT, ...)` → answer
   string (async HTTP). Budget check fires *before* the network call.
6. API returns `QueryResponse`. The CLI prints `answer`, and prints
   the chunks too if `--debug`.

Two network calls, both async, both budget-checked. Everything in
between is local and synchronous.

---

## 3. Locked decisions

### Async core, sync CLI

Async lives on exactly three Protocols: `Embedder`, `LLMProvider`,
`Retriever`. Everything else (`Chunker`, `DocumentLoader`,
`VectorStore`) is sync because it's either pure CPU or local disk.

The CLI is sync at its entry points and wraps the async core with
`asyncio.run(...)` exactly once per command. No mixing of paradigms
inside the CLI code itself.

### Chunk-ID ownership

The `VectorStore` is the authoritative source of int64 chunk IDs
(required by FAISS `IndexIDMap2`). Chunkers yield chunks with
`chunk_id = UNASSIGNED_CHUNK_ID`. The pipeline calls
`store.allocate_chunk_ids(n)` to atomically reserve a contiguous range,
then rebuilds the chunks with `dataclasses.replace` before
`store.add`. Mutation is contained to a single block in the pipeline.

### Soft-delete + explicit compaction

`DELETE /documents/{doc_id}` flips a tombstone flag in SQLite. The
FAISS index is never touched at delete time. Retrieval over-fetches
and filters tombstones. The on-disk FAISS index is only rewritten by
`POST /admin/compact` (or `pebble compact`), which the operator
schedules. There is no automatic compaction in v1.

### One container, no managed services

FAISS and SQLite live in the same process as FastAPI. No Postgres,
no Redis, no vector-DB service, no message broker. The deployment
artifact is one Docker image.

---

## 4. Module map

| Module                     | Owns                                              |
| -------------------------- | ------------------------------------------------- |
| `pebble/core/interfaces.py`| Protocols + dataclasses. No business logic.       |
| `pebble/core/errors.py`    | Typed exception taxonomy.                         |
| `pebble/core/ingestion.py` | Loaders, path walker, glob honouring.             |
| `pebble/core/chunking.py`  | Recursive character chunker.                      |
| `pebble/core/embeddings.py`| `Embedder` implementations (async httpx).         |
| `pebble/core/llm.py`       | `LLMProvider` implementations (async httpx).      |
| `pebble/core/retrieval.py` | `VectorRetriever`; `Hybrid` / `Graph` stubs.      |
| `pebble/core/store.py`     | FAISS `IndexIDMap2` + SQLite metadata.            |
| `pebble/core/prompts.py`   | The single locked prompt template.                |
| `pebble/core/budgets.py`   | Cost guards. Raises `BudgetExceededError`.        |
| `pebble/core/pipeline.py`  | Ingest pipeline + query pipeline, composed.       |
| `pebble/config/`           | YAML loading + Pydantic schema + env validation.  |
| `pebble/api/`              | FastAPI app, routes, request/response models, DI. |
| `pebble/cli/`              | Typer CLI. Sync at the edge.                      |
| `pebble/bootstrap.py`      | `build_app(config)` — the single wiring point.    |

---

## 5. Forward compatibility — MCP

An MCP adapter, when added, is a single file: `pebble/mcp.py`. It does
not introduce a new transport or duplicate business logic. It imports
the same handler functions the FastAPI routes call, exposes them as
MCP tools (`query`, `ingest`, `delete`, `compact`), and translates
between MCP's request envelope and Pebble's typed models. The
`asyncio` loop is shared with the surrounding host.

The forward-compatibility properties this needs from today's code are
already in place:

1. **No global state in handlers** — every endpoint resolves its
   dependencies via DI. An MCP tool builds the same dependencies.
2. **Typed pydantic request/response models** — these become the
   MCP tool input/output schemas with no transformation.
3. **One pipeline call per request** — the API layer is a thin
   translator. MCP becomes the same thin translator with a different
   envelope.

There is no `mcp/` directory in v1 and there will not be a separate
"MCP server" mode. When the time comes, `pebble.mcp:run` will be a
function that hosts the same handlers over MCP's stdio transport,
without ever starting FastAPI.

---

## 6. What this document does not cover

- Specific provider model choices (OpenAI vs. others) — config.
- Specific FAISS parameters (Flat vs. HNSW) — `store.py`. Default
  `IndexFlatIP` until corpora cross ~100k chunks; document the swap.
- Memory benchmark results — recorded by Agent H at the end of
  Phase 3, appended here.
