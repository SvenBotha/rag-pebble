"""Documents screen — list, ingest, delete, compact."""

from __future__ import annotations

import contextlib
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen  # type: ignore[import-untyped]
from textual.widgets import DataTable, Input, Label, Static

from pebble.tui.client import PebbleClient, PebbleClientError
from pebble.tui.widgets.progress import IngestComplete, IngestProgressBar


class _IngestInputScreen(ModalScreen):  # type: ignore[misc]
    """Modal dialog for entering one or more ingest paths."""

    DEFAULT_CSS = """
    _IngestInputScreen {
        align: center middle;
    }
    _IngestInputScreen #ingest-box {
        width: 60;
        height: 7;
        background: $surface;
        border: round $primary;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Static(id="ingest-box"):
            yield Label("Path(s) to ingest (comma-separated):")
            yield Input(placeholder="./docs  or  /absolute/path", id="path-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)  # type: ignore[misc]

    def on_key(self, event: Any) -> None:
        if hasattr(event, "key") and event.key == "escape":
            self.dismiss(None)  # type: ignore[misc]


class DocumentsScreen(Static):
    """Manages ingested documents: list, ingest new paths, delete, compact."""

    def compose(self) -> ComposeResult:
        table: DataTable[str] = DataTable(id="doc-table", cursor_type="row")
        table.add_columns("Source Path", "Chunks", "Ingested At")
        yield table
        yield IngestProgressBar(id="ingest-progress")
        yield Static(id="doc-status", classes="status-line")
        yield Static(
            "[i]ngest  [d]elete  [c]ompact  [r]efresh",
            id="doc-toolbar",
            markup=False,
        )

    def on_mount(self) -> None:
        self.run_worker(self._load(), name="doc-load")

    async def _load(self) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        table = self.query_one("#doc-table", DataTable)
        table.clear()
        try:
            data = await client.list_documents()
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Error loading documents: {exc}")
            return
        for doc in data.get("documents", []):
            table.add_row(
                doc["source_path"],
                str(doc["chunk_count"]),
                doc["created_at"][:19],
                key=doc["doc_id"],
            )
        total = data.get("total", 0)
        self._set_status(f"{total} document(s)")

    def _set_status(self, msg: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#doc-status", Static).update(msg)

    def _cursor_doc_id(self) -> str | None:
        table = self.query_one("#doc-table", DataTable)
        if table.row_count == 0:
            return None
        rows = table.ordered_rows
        if table.cursor_row >= len(rows):
            return None
        return str(rows[table.cursor_row].key.value)  # type: ignore[union-attr]

    def on_key(self, event: events.Key) -> None:
        """Handle key events bubbled up from the focused DataTable."""
        if event.key == "r":
            self.run_worker(self._load(), name="doc-load")
            event.stop()
        elif event.key == "i":
            self.run_worker(self._do_ingest(), name="doc-ingest-open")
            event.stop()
        elif event.key == "d":
            self.run_worker(self._do_delete(), name="doc-delete")
            event.stop()
        elif event.key == "c":
            self.run_worker(self._do_compact(), name="doc-compact")
            event.stop()

    async def _do_ingest(self) -> None:
        await self.app.push_screen(  # type: ignore[attr-defined]
            _IngestInputScreen(), callback=self._on_ingest_path
        )

    async def _on_ingest_path(self, path: str | None) -> None:
        if not path:
            return
        paths = [p.strip() for p in path.split(",") if p.strip()]
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        progress = self.query_one("#ingest-progress", IngestProgressBar)
        stream = client.ingest_stream()
        progress.start(stream)
        self.run_worker(
            client.ingest(paths if paths else None), name="ingest-run"
        )

    async def _do_delete(self) -> None:
        doc_id = self._cursor_doc_id()
        if not doc_id:
            return
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            result = await client.delete_document(doc_id)
            deleted = result.get("deleted_chunks", 0)
            self.app.notify(f"Deleted {deleted} chunk(s)", title="Documents")  # type: ignore[attr-defined]
        except PebbleClientError as exc:
            self.app.notify(f"Delete error: {exc.detail}", title="Documents", severity="error")  # type: ignore[attr-defined]
        self.run_worker(self._load(), name="doc-load")

    async def _do_compact(self) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        self._set_status("Compacting…")
        try:
            result = await client.compact()
            before = result.get("before", 0)
            after = result.get("after", 0)
            elapsed = result.get("elapsed_seconds", 0.0)
            self.app.notify(  # type: ignore[attr-defined]
                f"Compacted: {before} → {after} chunks in {elapsed:.2f}s",
                title="Documents",
            )
        except PebbleClientError as exc:
            self.app.notify(f"Compact error: {exc.detail}", title="Documents", severity="error")  # type: ignore[attr-defined]
        self.run_worker(self._load(), name="doc-load")

    def on_ingest_complete(self, event: IngestComplete) -> None:
        if event.success:
            self.app.notify("Ingest complete", title="Documents")  # type: ignore[attr-defined]
        else:
            self.app.notify(f"Ingest error: {event.detail}", title="Documents", severity="error")  # type: ignore[attr-defined]
        self.run_worker(self._load(), name="doc-load")
