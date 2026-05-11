.PHONY: sync dev run lint typecheck test all docker-build docker-run clean

sync:
	uv sync

dev:
	uv run uvicorn pebble.api.app:app --reload --host 0.0.0.0 --port 8000

run:
	uv run uvicorn pebble.api.app:app --host 0.0.0.0 --port 8000

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
	  -e OPENAI_API_KEY \
	  -v $$(pwd)/data:/app/data \
	  -v $$(pwd)/config.yaml:/app/config.yaml:ro \
	  pebble:latest

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
