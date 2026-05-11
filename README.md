# Pebble

A lightweight, API-first RAG system designed to run on a 1–2 GB VPS.

Pebble does retrieval locally (FAISS + SQLite) and delegates reasoning
to cloud LLMs. One container, one config file, no managed services.

Status: scaffolding. See `ARCHITECTURE.md` for the design and
`scripts/vertical_slice.py` for the simplest end-to-end reference.

## Development

```bash
uv sync
uv run pytest
```

Detailed docs land with Phase 2.
