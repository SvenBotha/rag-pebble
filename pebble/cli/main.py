"""Pebble CLI.

Two destinations:
- Queries (`ask`, `chat`) hit the HTTP API.
- Admin (`ingest`, `delete`, `compact`) call core directly via
  `asyncio.run` so the very first ingest works without a server.

The CLI is sync at its entry points and wraps the async core in exactly
one `asyncio.run` per command.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import typer

from pebble.api.models import ChunkOut, QueryRequest
from pebble.bootstrap import Services, build_services
from pebble.config.loader import load_config
from pebble.core.errors import PebbleError
from pebble.core.interfaces import Chunk, RetrievedChunk
from pebble.core.prompts import SYSTEM_PROMPT, assemble_user_message

DEFAULT_API_URL = "http://localhost:8000"
QUERY_TIMEOUT_S = 120.0

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Pebble — a small, API-first RAG system.",
)


def _api_url(override: str | None) -> str:
    return override or os.environ.get("PEBBLE_API_URL", DEFAULT_API_URL)


def _load_services(config_path: Path | None) -> Services:
    config = load_config(config_path)
    return build_services(config)


def _run_admin(coro_fn) -> None:  # type: ignore[no-untyped-def]
    """Run an admin command: load services, run coroutine, close client."""

    async def _wrapped() -> None:
        services = _load_services(None)
        try:
            await coro_fn(services)
        finally:
            await services.aclose()

    try:
        asyncio.run(_wrapped())
    except PebbleError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def ingest(
    path: list[Path] = typer.Argument(  # noqa: B008
        None,
        help="One or more paths to ingest. If omitted, uses sources.paths from config.",
    ),
    config: Path | None = typer.Option(None, "--config", help="Path to config.yaml."),
) -> None:
    """Ingest documents. Calls core directly — no running server needed."""

    async def _do(services: Services) -> None:
        paths = list(path) if path else None
        result = await services.ingest.ingest_paths(paths)
        typer.echo(
            f"ingested {result.ingested_documents} documents "
            f"({result.ingested_chunks} chunks), {result.skipped} skipped"
        )

    # _run_admin uses config from cwd; pass the override here.
    async def _wrapped() -> None:
        services = _load_services(config)
        try:
            await _do(services)
        finally:
            await services.aclose()

    try:
        asyncio.run(_wrapped())
    except PebbleError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def delete(
    doc_id: str = typer.Argument(..., help="Document ID to soft-delete."),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Soft-delete all chunks for a document. Calls core directly."""

    async def _wrapped() -> None:
        services = _load_services(config)
        try:
            deleted = services.query.delete_document(doc_id)
            typer.echo(f"soft-deleted {deleted} chunks for doc_id={doc_id}")
        finally:
            await services.aclose()

    try:
        asyncio.run(_wrapped())
    except PebbleError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def compact(
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Rebuild the FAISS index from live chunks. Calls core directly."""

    async def _wrapped() -> None:
        services = _load_services(config)
        try:
            result = services.query.compact()
            typer.echo(
                f"compacted: {result.before} → {result.after} rows "
                f"in {result.elapsed_seconds:.2f}s"
            )
        finally:
            await services.aclose()

    try:
        asyncio.run(_wrapped())
    except PebbleError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e


@app.command()
def ask(
    question: str = typer.Argument(..., help="The question to ask."),
    api_url: str | None = typer.Option(None, "--api-url"),
    debug: bool = typer.Option(False, "--debug", help="Print chunks and assembled prompt."),
) -> None:
    """Ask one question. Calls the HTTP API."""
    url = _api_url(api_url) + "/query"
    body = QueryRequest(query=question, debug=debug).model_dump()
    try:
        with httpx.Client(timeout=QUERY_TIMEOUT_S) as client:
            resp = client.post(url, json=body)
    except httpx.ConnectError:
        typer.echo(f"error: cannot reach {url} — is the API running?", err=True)
        raise typer.Exit(code=1) from None

    if resp.status_code != 200:
        typer.echo(f"error: HTTP {resp.status_code} — {resp.text[:300]}", err=True)
        raise typer.Exit(code=1)

    data = resp.json()
    typer.echo(data["answer"])
    if debug:
        _print_debug(question, data.get("chunks", []))


@app.command()
def chat(
    api_url: str | None = typer.Option(None, "--api-url"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    """REPL: type questions, press Ctrl-D or 'exit' to quit."""
    url = _api_url(api_url) + "/query"
    typer.echo("pebble chat — type a question, or 'exit' to quit.")
    with httpx.Client(timeout=QUERY_TIMEOUT_S) as client:
        while True:
            try:
                question = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                typer.echo("")
                break
            if not question or question.lower() in {"exit", "quit"}:
                break
            try:
                resp = client.post(url, json={"query": question, "debug": debug})
            except httpx.ConnectError:
                typer.echo(f"error: cannot reach {url}", err=True)
                continue
            if resp.status_code != 200:
                typer.echo(f"error: HTTP {resp.status_code} — {resp.text[:300]}", err=True)
                continue
            data = resp.json()
            typer.echo(data["answer"])
            if debug:
                _print_debug(question, data.get("chunks", []))


def _print_debug(query: str, chunks: list[dict[str, Any]]) -> None:
    if not chunks:
        typer.echo("\n[debug] no chunks returned")
        return
    typer.echo("\n[debug] retrieved chunks:")
    parsed = [ChunkOut.model_validate(c) for c in chunks]
    for c in parsed:
        typer.echo(f"  [{c.score:.3f}] {c.source_path}")
        typer.echo(f"    {c.text[:200]}{'…' if len(c.text) > 200 else ''}")

    # Rebuild the assembled prompt client-side using the same logic the
    # server used, so operators can see exactly what the LLM was given.
    placeholder_now = datetime.now()
    fake_hits = [
        RetrievedChunk(
            chunk=Chunk(
                chunk_id=i + 1,
                doc_id="",
                text=c.text,
                index=i,
                source_path=c.source_path,
                created_at=placeholder_now,
                metadata={},
            ),
            score=c.score,
        )
        for i, c in enumerate(parsed)
    ]
    assembled = assemble_user_message(query, fake_hits)
    typer.echo("\n[debug] system prompt:")
    typer.echo(SYSTEM_PROMPT)
    typer.echo("\n[debug] assembled user message:")
    typer.echo(assembled)


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(main())  # type: ignore[func-returns-value]
