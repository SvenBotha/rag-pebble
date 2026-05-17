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
from pebble.core.errors import PebbleError, StoreError
from pebble.core.interfaces import Chunk, RetrievedChunk
from pebble.core.pods import create_pod, delete_pod, list_pods, write_active_pod
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


def _load_services(config_path: Path | None, pod: str | None = None) -> Services:
    config = load_config(config_path)
    if pod is not None:
        config = config.model_copy(
            update={"storage": config.storage.model_copy(update={"active_pod": pod})}
        )
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
    pod: str | None = typer.Option(None, "--pod", help="Override active pod for this invocation."),
) -> None:
    """Ingest documents. Calls core directly — no running server needed."""

    async def _do(services: Services) -> None:
        paths = list(path) if path else None

        def _progress(_p: Path, docs: int, chunks: int) -> None:
            if docs == 1 or docs % 50 == 0:
                typer.echo(f"  ingested {docs} docs, {chunks} chunks…", err=True)

        result = await services.ingest.ingest_paths(paths, on_progress=_progress)
        typer.echo(
            f"ingested {result.ingested_documents} documents "
            f"({result.ingested_chunks} chunks), {result.skipped} skipped"
        )

    async def _wrapped() -> None:
        services = _load_services(config, pod=pod)
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
    pod: str | None = typer.Option(None, "--pod", help="Override active pod for this invocation."),
) -> None:
    """Soft-delete all chunks for a document. Calls core directly."""

    async def _wrapped() -> None:
        services = _load_services(config, pod=pod)
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
    pod: str | None = typer.Option(None, "--pod", help="Override active pod for this invocation."),
) -> None:
    """Rebuild the FAISS index from live chunks. Calls core directly."""

    async def _wrapped() -> None:
        services = _load_services(config, pod=pod)
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


pods_app = typer.Typer(no_args_is_help=True, help="Manage named pod stores.")
app.add_typer(pods_app, name="pods")


def _pods_dir_and_active(config_path: Path | None) -> tuple[Path, str]:
    config = load_config(config_path)
    return config.storage.pods_dir, config.storage.active_pod


@pods_app.command("list")
def pods_list(
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """List all pods with chunk count, size on disk, and active marker."""
    try:
        pods_dir, active_pod = _pods_dir_and_active(config)
        pods = list_pods(pods_dir, active_pod)
    except PebbleError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e

    if not pods:
        typer.echo("no pods found")
        return

    header = f"{'NAME':<30}  {'CHUNKS':>8}  {'SIZE MB':>8}  ACTIVE"
    typer.echo(header)
    typer.echo("-" * len(header))
    for p in pods:
        active_marker = "*" if p.active else ""
        typer.echo(f"{p.name:<30}  {p.chunk_count:>8}  {p.size_mb:>8.3f}  {active_marker}")


@pods_app.command("create")
def pods_create(
    name: str = typer.Argument(..., help="Name for the new pod."),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Create a new empty pod directory."""
    try:
        pods_dir, _ = _pods_dir_and_active(config)
        create_pod(pods_dir, name)
    except (PebbleError, StoreError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"created pod {name!r}")


@pods_app.command("delete")
def pods_delete(
    name: str = typer.Argument(..., help="Name of the pod to delete."),
    config: Path | None = typer.Option(None, "--config"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Delete a pod directory and all its data."""
    try:
        pods_dir, active_pod = _pods_dir_and_active(config)
    except PebbleError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e

    if name == active_pod:
        typer.echo(f"error: cannot delete the active pod {name!r}; switch first", err=True)
        raise typer.Exit(code=1)

    if not yes:
        confirmed = typer.confirm(f"Delete pod {name!r} and all its data?")
        if not confirmed:
            typer.echo("aborted")
            raise typer.Exit()

    try:
        delete_pod(pods_dir, name)
    except StoreError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e
    typer.echo(f"deleted pod {name!r}")


@pods_app.command("switch")
def pods_switch(
    name: str = typer.Argument(..., help="Name of the pod to activate."),
    config: Path | None = typer.Option(None, "--config"),
) -> None:
    """Set the active pod in config.yaml. Requires a server restart to take effect."""
    config_path = config
    if config_path is None:
        candidate = Path.cwd() / "config.yaml"
        if candidate.is_file():
            config_path = candidate

    try:
        pods_dir, _ = _pods_dir_and_active(config)
        pod_dir = pods_dir / name
        if not pod_dir.exists():
            typer.echo(f"error: pod {name!r} does not exist", err=True)
            raise typer.Exit(code=1)
        write_active_pod(config_path, name)
    except (PebbleError, StoreError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e

    if config_path is not None:
        typer.echo(f"active_pod set to {name!r} in {config_path}")
        typer.echo("restart the server for the change to take effect")
    else:
        typer.echo(
            f"no config.yaml found in cwd; set storage.active_pod: {name!r} manually and restart"
        )


def main() -> None:
    app()


if __name__ == "__main__":
    sys.exit(main())  # type: ignore[func-returns-value]
