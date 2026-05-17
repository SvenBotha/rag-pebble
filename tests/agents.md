# tests/ — Agent Context

35 tests, fully offline. No API key needed. Run with `uv run pytest`.

## Test files

| File | Covers |
|------|--------|
| `test_chunking.py` | `RecursiveCharacterChunker` — edge cases, overlap, metadata |
| `test_retrieval.py` | `FaissSqliteStore` — add/search/delete/compact/has_document, round-trips with real FAISS |
| `test_budgets.py` | `enforce_query_budget`, `enforce_ingest_budget` |
| `test_api.py` | FastAPI routes via `TestClient` with injected stub services |
| `conftest.py` | `StubEmbedder`, `StubLLM`, `tmp_store_paths` fixture |

## Stubs (`conftest.py`)

**`StubEmbedder`** — deterministic 16-dim embeddings via SHA-256 hash of text. Same text always → same vector. Does not call OpenAI.

**`StubLLM`** — returns `"stub answer (received N chars of context)"`. Does not call OpenAI.

**`STUB_DIM = 16`** — use this constant when constructing test stores. Never use the real 1536 in tests (slow FAISS allocation).

## Patterns for API tests

Build a `FastAPI` app manually with injected services — skip the real lifespan:

```python
@pytest.fixture
def test_app(tmp_path, stub_embedder, stub_llm) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.start_time = time.time()
    app.state.services = _build_services(tmp_path, stub_embedder, stub_llm)
    app.state.ready = True
    app.state.ready_error = None
    return app

@pytest.fixture
def client(test_app) -> TestClient:
    return TestClient(test_app)
```

For tests that need budget errors, construct a real `OpenAILLM` with `max_tokens_per_query=10` and a fake API key — the budget check fires before any network call.

## Patterns for store tests

Use real FAISS + real SQLite against `tmp_path` — no mocking:

```python
@pytest.fixture
def store(tmp_store_paths) -> FaissSqliteStore:
    index_path, meta_path = tmp_store_paths
    s = FaissSqliteStore(index_path=index_path, metadata_path=meta_path, dim=DIM)
    s.load()
    return s
```

Use `_rand_vec(seed)` for reproducible random vectors and `replace(_chunk(...), chunk_id=store.allocate_chunk_ids(1))` for assigned-ID chunks.

## What tests to add

When adding pods support:
- `test_pods.py` — `list_pods`, `create_pod`, `delete_pod`, pod path resolution from config
- Pod-aware API endpoint tests in `test_api.py`

When adding TUI:
- `test_tui.py` — use `App.run_test()` with mocked `PebbleClient`

## `asyncio_mode = "auto"` is configured

All `async def test_*` functions are automatically collected and run. No `@pytest.mark.asyncio` decorator needed.
