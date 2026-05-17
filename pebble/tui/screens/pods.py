"""Pods screen — list, create, delete, and activate pods."""

from __future__ import annotations

import contextlib
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen  # type: ignore[import-untyped]
from textual.widgets import DataTable, Input, Label, Static

from pebble.tui.client import PebbleClient, PebbleClientError


class _PodNameScreen(ModalScreen):  # type: ignore[misc]
    """Modal dialog for entering a pod name."""

    DEFAULT_CSS = """
    _PodNameScreen {
        align: center middle;
    }
    _PodNameScreen #pod-box {
        width: 50;
        height: 7;
        background: $surface;
        border: round $primary;
        padding: 1 2;
    }
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Static(id="pod-box"):
            yield Label(self._title)
            yield Input(placeholder="pod-name", id="pod-name-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)  # type: ignore[misc]

    def on_key(self, event: Any) -> None:
        if hasattr(event, "key") and event.key == "escape":
            self.dismiss(None)  # type: ignore[misc]


class PodsScreen(Static):
    """Manage named FAISS+SQLite pod stores."""

    def compose(self) -> ComposeResult:
        table: DataTable[str] = DataTable(id="pod-table", cursor_type="row")
        table.add_columns("Pod Name", "Chunks", "Size (MB)", "Active")
        yield table
        yield Static(id="pod-status", classes="status-line")
        # Use markup=False so brackets are displayed literally, not as Rich tags.
        yield Static(
            "[n]ew  [d]elete  [a]ctivate  [r]efresh",
            id="pod-toolbar",
            markup=False,
        )

    def on_mount(self) -> None:
        self.run_worker(self._load(), name="pod-load")

    async def _load(self) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        table = self.query_one("#pod-table", DataTable)
        table.clear()
        try:
            pods = await client.list_pods()
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Error loading pods: {exc}")
            return
        for pod in pods:
            active = "* active" if pod.get("active") else ""
            table.add_row(
                pod["name"],
                str(pod.get("chunk_count", 0)),
                f"{pod.get('size_mb', 0.0):.3f}",
                active,
                key=pod["name"],
            )
        self._set_status(f"{len(pods)} pod(s)")

    def _set_status(self, msg: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#pod-status", Static).update(msg)

    def _cursor_pod_name(self) -> str | None:
        table = self.query_one("#pod-table", DataTable)
        if table.row_count == 0:
            return None
        rows = table.ordered_rows
        if table.cursor_row >= len(rows):
            return None
        return str(rows[table.cursor_row].key.value)  # type: ignore[union-attr]

    def on_key(self, event: events.Key) -> None:
        """Handle key events bubbled up from the focused DataTable."""
        if event.key == "r":
            self.run_worker(self._load(), name="pod-load")
            event.stop()
        elif event.key == "n":
            self.run_worker(self._do_new_pod(), name="pod-new")
            event.stop()
        elif event.key == "d":
            self.run_worker(self._do_delete_pod(), name="pod-delete")
            event.stop()
        elif event.key == "a":
            self.run_worker(self._do_activate_pod(), name="pod-activate")
            event.stop()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on DataTable row triggers activate."""
        self.run_worker(self._do_activate_pod(), name="pod-activate")

    async def _do_new_pod(self) -> None:
        await self.app.push_screen(  # type: ignore[attr-defined]
            _PodNameScreen("Create new pod"), callback=self._on_create
        )

    async def _on_create(self, name: str | None) -> None:
        if not name:
            return
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            await client.create_pod(name)
            self.app.notify(f"Created pod '{name}'", title="Pods")  # type: ignore[attr-defined]
        except PebbleClientError as exc:
            self.app.notify(f"Create error: {exc.detail}", title="Pods", severity="error")  # type: ignore[attr-defined]
        self.run_worker(self._load(), name="pod-load")

    async def _do_delete_pod(self) -> None:
        name = self._cursor_pod_name()
        if not name:
            return
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            await client.delete_pod(name)
            self.app.notify(f"Deleted pod '{name}'", title="Pods")  # type: ignore[attr-defined]
        except PebbleClientError as exc:
            self.app.notify(f"Delete error: {exc.detail}", title="Pods", severity="error")  # type: ignore[attr-defined]
        self.run_worker(self._load(), name="pod-load")

    async def _do_activate_pod(self) -> None:
        name = self._cursor_pod_name()
        if not name:
            return
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            result = await client.activate_pod(name)
            msg = result.get("message", f"Activated '{name}'")
            self.app.notify(msg, title="Pods", timeout=8)  # type: ignore[attr-defined]
        except PebbleClientError as exc:
            self.app.notify(f"Activate error: {exc.detail}", title="Pods", severity="error")  # type: ignore[attr-defined]
        self.run_worker(self._load(), name="pod-load")
