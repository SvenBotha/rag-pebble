# pebble/ — Package Agent Context

The `pebble/` package contains all production code. Tests live in `tests/`, benchmarks in `bench/`.

## Structure

```
pebble/
├── core/        # domain logic — no FastAPI, no Typer, no HTTP framework imports
├── config/      # YAML loading + Pydantic schema
├── api/         # FastAPI app, routes, DI
├── cli/         # Typer CLI entry points
├── tui/         # Textual TUI (to be built)
└── bootstrap.py # the single wiring point
```

## Key rule: import direction

```
core ← config ← bootstrap ← api
                           ← cli
                           ← tui
```

`core` must never import from `api`, `cli`, or `tui`. `bootstrap` is the only module that knows about concrete implementations. Nothing in `api/`, `cli/`, or `tui/` should construct services directly — always go through `bootstrap.build_services(config)`.

## Adding a new provider

1. Add a new implementation in the relevant `core/` module (e.g. `core/embeddings.py` for a new embedder).
2. Register it in `bootstrap.py` under the appropriate `_build_*` function.
3. Add the provider name to the `Provider` literal in `config/schema.py`.
4. Add env-var validation in `config/loader.py:PROVIDER_ENV_VARS`.

## Adding a new API endpoint

1. Add the route in `pebble/api/routes.py`.
2. Add request/response Pydantic models in `pebble/api/models.py`.
3. If it needs `Services`, use `Depends(require_services)` from `pebble/api/deps.py`.
4. If it raises a new error type, add an exception handler in `pebble/api/app.py:_install_error_handlers`.

## What needs to be added (see root `agents.md` for full plan)

- `pebble/core/pods.py` — pod listing, creation, deletion helpers
- `pebble/tui/` — full Textual TUI (see `pebble/tui/agents.md`)
- New API endpoints in `routes.py`: `/documents`, `/pods`, `/config`, `/admin/reload`, `/ingest/stream`
- New config fields in `config/schema.py`: `pods_dir`, `active_pod`
- New CLI commands in `cli/main.py`: `pebble pods`, `pebble tui`, `--pod` flag on existing commands
