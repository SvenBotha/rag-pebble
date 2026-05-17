# pebble/core/ — Agent Context

Domain logic only. No framework imports (FastAPI, Typer, Textual). No network calls except through `Embedder` and `LLMProvider` Protocol implementations.

## Existing files

| File | Purpose |
|------|---------|
| `interfaces.py` | Protocols + frozen dataclasses. The contract surface. Read this first. |
| `errors.py` | Exception taxonomy. All cross-module errors must be typed subclasses here. |
| `pipeline.py` | `IngestPipeline` + `QueryPipeline`. The composed flows. |
| `store.py` | `FaissSqliteStore` — FAISS IndexIDMap2 + SQLite. Soft-deletes, atomic ID allocation. |
| `embeddings.py` | `OpenAIEmbedder` — async httpx, batched, budget-checked. |
| `llm.py` | `OpenAILLM` — async httpx, budget-checked. |
| `_http.py` | Shared retry/error-mapping (tenacity). All cloud HTTP calls go through here. |
| `retrieval.py` | `VectorRetriever` (live), `HybridRetriever`/`GraphRetriever` (stubs). |
| `chunking.py` | `RecursiveCharacterChunker`. |
| `ingestion.py` | Loaders (txt/md/pdf), path walker, `doc_id_for(path)`. |
| `prompts.py` | The single prompt template + `assemble_user_message`. |
| `budgets.py` | `enforce_query_budget`, `enforce_ingest_budget`. Fire before network calls. |

## Protocols and async rules

**Async**: `Embedder.embed`, `LLMProvider.complete`, `Retriever.retrieve`
**Sync**: `Chunker.chunk`, `DocumentLoader.load`, all `VectorStore` methods

This is locked. Do not make `VectorStore` async — FAISS and SQLite are local, adding asyncio would just add a thread-pool hop.

## Chunk ID lifecycle

1. `Chunker.chunk(doc)` yields `Chunk(chunk_id=UNASSIGNED_CHUNK_ID, ...)`
2. Pipeline calls `store.allocate_chunk_ids(n)` — returns first int64 in a reserved range
3. Pipeline calls `dataclasses.replace(chunk, chunk_id=start + i)` for each chunk
4. Pipeline calls `store.add(chunks, vectors)`

Never modify this pattern. The atomic `UPDATE ... RETURNING` in `store.allocate_chunk_ids` prevents ID collisions across concurrent processes.

## What needs to be added

### `pebble/core/pods.py` (new file)

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class PodInfo:
    name: str
    chunk_count: int
    size_mb: float
    active: bool

def list_pods(pods_dir: Path, active_pod: str) -> list[PodInfo]:
    """Scan pods_dir, open each pod's SQLite to get chunk count."""
    ...

def create_pod(pods_dir: Path, name: str) -> None:
    """mkdir pods_dir/name. Raise if exists."""
    ...

def delete_pod(pods_dir: Path, name: str) -> None:
    """rm -rf pods_dir/name. Raise if active pod."""
    ...
```

`list_pods` should open each pod's SQLite (read-only) to get `COUNT(*) WHERE deleted=0`. Do not load FAISS for listing — it's too expensive.

## Store internals worth knowing

- Vectors are L2-normalised on `add()` — the store normalises defensively even if the caller already normalised.
- `search()` over-fetches by `2× + 5` to compensate for tombstones, then filters via a single SQLite `IN (...)` query.
- `compact()` uses `index.reconstruct(id)` on `IndexIDMap2` to recover vectors — this is why `IndexIDMap2` is required over plain `IndexIDMap`.
- The `threading.RLock` serialises all store operations. Safe for multi-threaded FastAPI; not a substitute for multi-process safety (use the atomic SQL for that).
