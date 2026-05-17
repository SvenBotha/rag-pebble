# bench/ — Agent Context

Load testing tools for the §8 acceptance criteria (RSS < 400 MB at 50k chunks). Requires `OPENAI_API_KEY` and the `bench` dependency group (`make bench-sync`).

## Files

| File | Purpose |
|------|---------|
| `prepare_corpus.py` | Streams Simple English Wikipedia from HuggingFace, writes articles as `.md` files to `./data/corpus/` |
| `run_load_test.py` | Ingests corpus via normal pipeline, runs concurrent queries, reports RSS vs 400 MB target |

## Important operational notes

**Run only one bench process at a time.** Even with the atomic ID allocator, two concurrent ingest processes will duplicate documents (idempotent check + insert is not atomic across processes). Concurrent processes caused data corruption during development.

**`ru_maxrss` reports peak RSS**, not current. The peak during ingest is higher than load-only RSS because the async HTTP heap grows during embedding calls (~200 MB extra). The §8 target applies to load-only RSS (server startup with pre-built index), not ingest-time RSS.

## Scale guidance

| Target | Articles (Simple Wikipedia) | Expected chunks | Ingest time |
|--------|----------------------------|-----------------|-------------|
| Smoke test | 1,000 | ~7,000 | ~8 min (pre-batching) / ~1 min (post-batching) |
| §8 target (50k chunks) | ~12,000 | ~50,000 | ~4 min |
| Full test (102k chunks) | 25,000 | ~102,000 | ~51 min |

## Crash recovery

If a run is interrupted:
1. Kill all bench processes: `ps aux | grep run_load_test`
2. Wipe the store: `rm -f data/pebble.index data/pebble.meta.sqlite data/pebble.meta.sqlite-shm data/pebble.meta.sqlite-wal`
3. Re-run from scratch

With idempotent ingestion, re-running skips already-ingested docs automatically — but only if the SQLite is consistent with the FAISS index. If a run was interrupted mid-ingest (SQLite committed, FAISS not persisted), wipe and restart.

## Adding new bench scenarios

Add new scripts to `bench/`. They can import `pebble.*` directly since uv puts the package on the path. Use `from dotenv import load_dotenv; load_dotenv()` at the top of `main()` before checking for API keys.
