# pebble/config/ — Agent Context

YAML loading, env-var validation, and Pydantic schema.

## Files

| File | Purpose |
|------|---------|
| `schema.py` | Pydantic models for the full config. Every field has a default. |
| `loader.py` | `load_config(path) → PebbleConfig`. Calls `load_dotenv()`. Validates env vars per provider. |

## Schema changes needed: Pods support

Replace `StorageConfig` with pod-aware paths. Maintain backwards compatibility — if the user's `config.yaml` has the old `index_path`/`metadata_path` fields directly, still honour them.

```python
class StorageConfig(BaseModel):
    # New pod-based fields
    pods_dir: Path = Path("./data/pods")
    active_pod: str = "default"

    # Legacy fields (deprecated but still honoured)
    index_path: Path | None = None
    metadata_path: Path | None = None

    @property
    def resolved_index_path(self) -> Path:
        if self.index_path is not None:
            return self.index_path  # backwards compat
        return self.pods_dir / self.active_pod / "pebble.index"

    @property
    def resolved_metadata_path(self) -> Path:
        if self.metadata_path is not None:
            return self.metadata_path  # backwards compat
        return self.pods_dir / self.active_pod / "pebble.meta.sqlite"
```

Update `bootstrap.py` to use `resolved_index_path` and `resolved_metadata_path`.

## Adding a new config field

1. Add to the appropriate Pydantic model in `schema.py` with a sensible default.
2. Update `examples/config.yaml` with the new field and a comment.
3. If the field requires an env var, add to `PROVIDER_ENV_VARS` in `loader.py`.
4. `model_config = {"extra": "forbid"}` is set on `PebbleConfig` — unknown keys will error.

## Config fields that require re-ingest when changed

If the TUI or any tool writes to config.yaml, it must warn the user when these fields change:

| Field | Reason |
|-------|--------|
| `embeddings.model` | Existing vectors are in the old model's space; incompatible |
| `embeddings.dim` (future) | FAISS index dimension changes |
| `chunking.chunk_size` | Existing chunks don't match new split boundaries |
| `chunking.overlap` | Same as above |
| `storage.active_pod` | Different pod = different index |

Fields that are safe to change live (no re-ingest): `llm.*`, `retrieval.top_k`, `retrieval.similarity_threshold`, `limits.*`, `debug.*`.
