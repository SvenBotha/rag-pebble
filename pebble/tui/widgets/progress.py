"""Ingest progress widget fed by SSE events from GET /ingest/stream."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Label, ProgressBar, Static


class IngestComplete(Message):
    """Posted to the app when ingest finishes (complete or error)."""

    def __init__(self, success: bool, detail: str = "") -> None:
        super().__init__()
        self.success = success
        self.detail = detail


class IngestProgressBar(Static):
    """Shows a progress bar + stats during ingest.

    Call `start(stream)` with an async iterator of SSE events. Hidden by
    default; shows itself when ingest starts and hides again on completion.
    """

    def compose(self) -> ComposeResult:
        yield ProgressBar(total=None, show_eta=False, id="ingest-bar")
        yield Label("", id="ingest-stats")
        yield Label("Starting ingest…", id="ingest-status")

    def start(self, stream: AsyncIterator[dict[str, Any]]) -> None:
        self.add_class("active")
        try:
            self.query_one("#ingest-stats", Label).update("")
            self.query_one("#ingest-status", Label).update("Connecting…")
        except Exception:  # noqa: BLE001
            pass
        self.run_worker(self._consume(stream), exclusive=True, name="ingest-stream")

    async def _consume(self, stream: AsyncIterator[dict[str, Any]]) -> None:
        status_label = self.query_one("#ingest-status", Label)
        stats_label = self.query_one("#ingest-stats", Label)
        progress_bar = self.query_one("#ingest-bar", ProgressBar)
        try:
            async for event in stream:
                t = event.get("type", "")
                if t == "progress":
                    docs = event.get("docs", 0)
                    chunks = event.get("chunks", 0)
                    elapsed = event.get("elapsed_s", 0.0)
                    stats_label.update(
                        f"[green]{docs}[/green] docs  "
                        f"[green]{chunks}[/green] chunks  "
                        f"[dim]{elapsed:.1f}s[/dim]"
                    )
                    status_label.update("Embedding…")
                    progress_bar.advance(1)
                elif t == "complete":
                    ingested = event.get("ingested_documents", 0)
                    ichunks = event.get("ingested_chunks", 0)
                    stats_label.update(
                        f"[green]{ingested}[/green] docs  "
                        f"[green]{ichunks}[/green] chunks"
                    )
                    status_label.update("[green]Done[/green]")
                    self.post_message(IngestComplete(success=True))
                    break
                elif t == "error":
                    msg = event.get("message", "unknown error")
                    status_label.update(f"[red]Error: {msg}[/red]")
                    self.post_message(IngestComplete(success=False, detail=msg))
                    break
        except Exception as exc:  # noqa: BLE001
            status_label.update(f"[red]Stream error: {exc}[/red]")
            self.post_message(IngestComplete(success=False, detail=str(exc)))
        finally:
            self.remove_class("active")
