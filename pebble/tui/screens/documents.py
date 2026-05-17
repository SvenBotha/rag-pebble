"""Documents screen — list, delete, and compact documents."""

from __future__ import annotations

import contextlib

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Label, Static

from pebble.tui.client import PebbleClient, PebbleClientError
from pebble.tui.screens.confirm import ConfirmScreen


class DocumentsScreen(Static):
    """Manages ingested documents: list, delete, compact."""

    BINDINGS = [
        Binding("d", "delete_doc", "Delete", priority=True),
        Binding("c", "compact", "Compact", priority=True),
        Binding("r", "refresh", "Refresh", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Label("", id="doc-summary")
        table: DataTable[str] = DataTable(id="doc-table", cursor_type="row")
        table.add_columns("Source Path", "Chunks", "Ingested At")
        yield table
        yield Label("", id="doc-status", classes="status-line")
        yield Static(
            "[d]=delete  [c]=compact  [r]=refresh",
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

        total_chunks = 0
        for doc in data.get("documents", []):
            chunks = doc["chunk_count"]
            total_chunks += chunks
            table.add_row(
                doc["source_path"],
                str(chunks),
                doc["created_at"][:19],
                key=doc["doc_id"],
            )

        total = data.get("total", 0)
        self.query_one("#doc-summary", Label).update(
            f"[dim]{total} document(s)  ·  {total_chunks:,} chunks total[/dim]"
        )
        self._set_status(f"{total} document(s)")

    def _set_status(self, msg: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#doc-status", Label).update(msg)

    def _cursor_doc_id(self) -> str | None:
        table = self.query_one("#doc-table", DataTable)
        if table.row_count == 0:
            return None
        rows = table.ordered_rows
        if table.cursor_row >= len(rows):
            return None
        return str(rows[table.cursor_row].key.value)  # type: ignore[union-attr]

    def _cursor_source_path(self) -> str:
        table = self.query_one("#doc-table", DataTable)
        if table.row_count == 0:
            return ""
        rows = table.ordered_rows
        if table.cursor_row >= len(rows):
            return ""
        # Source path is the first cell value
        try:
            return str(table.get_row(rows[table.cursor_row].key)[0])
        except Exception:  # noqa: BLE001
            return ""

    def action_refresh(self) -> None:
        self.run_worker(self._load(), name="doc-load")

    def action_delete_doc(self) -> None:
        self.run_worker(self._do_delete(), name="doc-delete")

    def action_compact(self) -> None:
        self.run_worker(self._do_compact(), name="doc-compact")


    async def _do_delete(self) -> None:
        doc_id = self._cursor_doc_id()
        if not doc_id:
            return
        path = self._cursor_source_path() or doc_id

        async def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            client: PebbleClient = self.app.client  # type: ignore[attr-defined]
            try:
                result = await client.delete_document(doc_id)
                deleted = result.get("deleted_chunks", 0)
                self.app.notify(f"Deleted {deleted} chunk(s)", title="Documents")  # type: ignore[attr-defined]
            except PebbleClientError as exc:
                self.app.notify(  # type: ignore[attr-defined]
                    f"Delete error: {exc.detail}",
                    title="Documents",
                    severity="error",
                )
            self.run_worker(self._load(), name="doc-load")

        await self.app.push_screen(  # type: ignore[attr-defined]
            ConfirmScreen(f"Delete '{path}' and all its chunks?"),
            callback=_on_confirm,
        )

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
            self.app.notify(  # type: ignore[attr-defined]
                f"Compact error: {exc.detail}",
                title="Documents",
                severity="error",
            )
        self.run_worker(self._load(), name="doc-load")
