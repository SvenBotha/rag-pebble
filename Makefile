.PHONY: sync dev run tui ingest lint typecheck test all docker-build docker-run clean \
        bench-sync bench-prepare bench-run

sync:
	uv sync

dev:
	uv run uvicorn pebble.api.app:app --reload --host 0.0.0.0 --port 8000

run:
	uv run uvicorn pebble.api.app:app --host 0.0.0.0 --port 8000

tui:
	uv run pebble tui $(ARGS)

ingest:
	uv run pebble ingest $(ARGS)

lint:
	uv run ruff check pebble tests

typecheck:
	uv run mypy pebble

test:
	uv run pytest

all: lint typecheck test

docker-build:
	docker build -t pebble:latest .

docker-run:
	docker run --rm -p 8000:8000 \
	  --env-file .env \
	  -v $$(pwd)/data:/app/data \
	  -v $$(pwd)/config.yaml:/app/config.yaml:ro \
	  pebble:latest

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

# --- load testing (§8 acceptance) ---
bench-sync:
	uv sync --group bench

bench-prepare:
	uv run --group bench python bench/prepare_corpus.py $(ARGS)

bench-run:
	uv run --group bench python bench/run_load_test.py $(ARGS)
