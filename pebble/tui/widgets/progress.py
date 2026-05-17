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
    """Shows an indeterminate progress bar + status text during ingest.

    Call `start(stream)` with an async iterator of SSE events. Hidden by
    default; shows itself when ingest starts and hides again on completion.
    """

    DEFAULT_CSS = """
    IngestProgressBar {
        height: 3;
        display: none;
        padding: 0 1;
    }
    IngestProgressBar.active {
        display: block;
    }
    IngestProgressBar ProgressBar {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield ProgressBar(total=None, show_eta=False)
        yield Label("Starting ingest…", id="ingest-status")

    def start(self, stream: AsyncIterator[dict[str, Any]]) -> None:
        self.add_class("active")
        self.query_one("#ingest-status", Label).update("Starting ingest…")
        self.run_worker(self._consume(stream), exclusive=True, name="ingest-stream")

    async def _consume(self, stream: AsyncIterator[dict[str, Any]]) -> None:
        status_label = self.query_one("#ingest-status", Label)
        progress_bar = self.query_one(ProgressBar)
        try:
            async for event in stream:
                t = event.get("type", "")
                if t == "progress":
                    docs = event.get("docs", 0)
                    chunks = event.get("chunks", 0)
                    elapsed = event.get("elapsed_s", 0.0)
                    status_label.update(
                        f"{docs} docs, {chunks} chunks, {elapsed:.1f}s"
                    )
                    progress_bar.advance(1)
                elif t == "complete":
                    ingested = event.get("ingested_documents", 0)
                    ichunks = event.get("ingested_chunks", 0)
                    status_label.update(
                        f"Done: {ingested} docs, {ichunks} chunks"
                    )
                    self.post_message(IngestComplete(success=True))
                    break
                elif t == "error":
                    msg = event.get("message", "unknown error")
                    status_label.update(f"Error: {msg}")
                    self.post_message(IngestComplete(success=False, detail=msg))
                    break
        except Exception as exc:  # noqa: BLE001
            status_label.update(f"Stream error: {exc}")
            self.post_message(IngestComplete(success=False, detail=str(exc)))
        finally:
            self.remove_class("active")
