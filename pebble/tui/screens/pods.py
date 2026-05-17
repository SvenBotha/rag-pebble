"""Pods screen — list, create, delete, and activate pods."""

from __future__ import annotations

import contextlib

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Input, Label, Static

from pebble.tui.client import PebbleClient, PebbleClientError
from pebble.tui.screens.confirm import ConfirmScreen


class PodsScreen(Static):
    """Manage named FAISS+SQLite pod stores."""

    BINDINGS = [
        Binding("n", "new_pod", "New pod", priority=True),
        Binding("d", "delete_pod", "Delete", priority=True),
        Binding("a", "activate_pod", "Activate", priority=True),
        Binding("r", "refresh", "Refresh", priority=True),
    ]

    def compose(self) -> ComposeResult:
        table: DataTable[str] = DataTable(id="pod-table", cursor_type="row")
        table.add_columns("Pod Name", "Chunks", "Size (MB)", "Active")
        yield table
        yield Label("", id="pod-status", classes="status-line")
        with Static(id="pod-inline-input"):
            yield Label("New pod name:", id="pod-inline-label")
            yield Input(placeholder="pod-name", id="pod-name-input")
        yield Static(
            "[n]=new  [d]=delete  [a/Enter]=activate  [r]=refresh",
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
            is_active = pod.get("active", False)
            active_marker = "[green]● active[/green]" if is_active else ""
            table.add_row(
                f"[bold]{pod['name']}[/bold]" if is_active else pod["name"],
                str(pod.get("chunk_count", 0)),
                f"{pod.get('size_mb', 0.0):.3f}",
                active_marker,
                key=pod["name"],
            )
        self._set_status(f"{len(pods)} pod(s)")

    def _set_status(self, msg: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#pod-status", Label).update(msg)

    def _cursor_pod_name(self) -> str | None:
        table = self.query_one("#pod-table", DataTable)
        if table.row_count == 0:
            return None
        rows = table.ordered_rows
        if table.cursor_row >= len(rows):
            return None
        return str(rows[table.cursor_row].key.value)  # type: ignore[union-attr]

    def _show_new_pod_input(self) -> None:
        row = self.query_one("#pod-inline-input", Static)
        row.add_class("visible")
        self.query_one("#pod-name-input", Input).focus()

    def _hide_new_pod_input(self) -> None:
        row = self.query_one("#pod-inline-input", Static)
        row.remove_class("visible")
        self.query_one("#pod-name-input", Input).value = ""

    def action_new_pod(self) -> None:
        inline = self.query_one("#pod-inline-input", Static)
        if "visible" not in inline.classes:
            self._show_new_pod_input()

    def action_delete_pod(self) -> None:
        inline = self.query_one("#pod-inline-input", Static)
        if "visible" not in inline.classes:
            self.run_worker(self._do_delete_pod(), name="pod-delete")

    def action_activate_pod(self) -> None:
        inline = self.query_one("#pod-inline-input", Static)
        if "visible" not in inline.classes:
            self.run_worker(self._do_activate_pod(), name="pod-activate")

    def action_refresh(self) -> None:
        inline = self.query_one("#pod-inline-input", Static)
        if "visible" not in inline.classes:
            self.run_worker(self._load(), name="pod-load")

    def on_key(self, event: events.Key) -> None:
        """Handle escape to dismiss inline input, and enter for activate."""
        inline = self.query_one("#pod-inline-input", Static)
        if "visible" in inline.classes:
            if event.key == "escape":
                self._hide_new_pod_input()
                event.stop()
        elif event.key == "enter":
            self.run_worker(self._do_activate_pod(), name="pod-activate")
            event.stop()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "pod-name-input":
            name = event.value.strip()
            self._hide_new_pod_input()
            if name:
                self.run_worker(self._do_create_pod(name), name="pod-create")
            event.stop()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.run_worker(self._do_activate_pod(), name="pod-activate")

    async def _do_create_pod(self, name: str) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            await client.create_pod(name)
            self.app.notify(f"Created pod '{name}'", title="Pods")  # type: ignore[attr-defined]
        except PebbleClientError as exc:
            self.app.notify(  # type: ignore[attr-defined]
                f"Create error: {exc.detail}",
                title="Pods",
                severity="error",
            )
        self.run_worker(self._load(), name="pod-load")

    async def _do_delete_pod(self) -> None:
        name = self._cursor_pod_name()
        if not name:
            return

        async def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            client: PebbleClient = self.app.client  # type: ignore[attr-defined]
            try:
                await client.delete_pod(name)
                self.app.notify(f"Deleted pod '{name}'", title="Pods")  # type: ignore[attr-defined]
            except PebbleClientError as exc:
                self.app.notify(  # type: ignore[attr-defined]
                    f"Delete error: {exc.detail}",
                    title="Pods",
                    severity="error",
                )
            self.run_worker(self._load(), name="pod-load")

        await self.app.push_screen(  # type: ignore[attr-defined]
            ConfirmScreen(f"Delete pod '{name}' and all its data?"),
            callback=_on_confirm,
        )

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
            self.app.notify(  # type: ignore[attr-defined]
                f"Activate error: {exc.detail}",
                title="Pods",
                severity="error",
            )
        self.run_worker(self._load(), name="pod-load")
