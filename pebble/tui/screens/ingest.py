"""Ingest screen — run ingestion and manage pods in one place."""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Input, Label, ListItem, ListView, Select, Static

from pebble.tui.client import PebbleClient, PebbleClientError
from pebble.tui.widgets.progress import IngestComplete, IngestProgressBar

_NEW_POD_SENTINEL = "__new__"


def _now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


class IngestScreen(Static):
    """Unified ingest + pod management screen."""

    BINDINGS = [
        Binding("n", "new_pod", "New pod", priority=True),
        Binding("a", "add_path", "Add path", priority=True),
        Binding("d", "remove_path", "Remove path", priority=True),
        Binding("r", "refresh_pods", "Refresh", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._pods: list[dict[str, Any]] = []
        self._history: list[tuple[str, str, int, int, str]] = []  # time, pod, docs, chunks, status

    def compose(self) -> ComposeResult:
        yield Label("INGEST", id="ingest-header")

        # ── Pod selector row
        with Static(id="pod-row"):
            yield Label("Target pod:")
            yield Select(
                [("default", "default")],
                id="pod-select",
                allow_blank=False,
                value="default",
            )
            yield Label("  [n] new pod", id="new-pod-btn", markup=True)
            yield Input(placeholder="new-pod-name", id="new-pod-input")

        # ── Paths section
        yield Label("Paths to ingest:", id="paths-label")
        yield ListView(id="paths-list")
        with Static(id="path-input-row"):
            yield Input(placeholder="./path/to/docs  or  /absolute/path", id="path-input")

        # ── Progress section
        yield Label("Progress:", id="progress-label")
        yield IngestProgressBar(id="ingest-progress")
        yield Label("", id="ingest-status-line")

        # ── History section
        yield Label("Recent ingestions:", id="history-label")
        table: DataTable[str] = DataTable(id="history-table", cursor_type="row", show_cursor=False)
        table.add_columns("Time", "Pod", "Docs", "Chunks", "Status")
        yield table

        yield Static(
            "[Enter]=ingest  [a]=add path  [d]=remove path  [n]=new pod  [r]=refresh pods",
            id="ingest-toolbar",
            markup=False,
        )

    def on_mount(self) -> None:
        self.run_worker(self._load_pods(), name="ingest-pod-load")

    async def _load_pods(self) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            self._pods = await client.list_pods()
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Error loading pods: {exc}")
            return

        select = self.query_one("#pod-select", Select)
        options = [(p["name"], p["name"]) for p in self._pods]
        if not options:
            options = [("default", "default")]
        select.set_options(options)

        # Pre-select the active pod
        active = next((p["name"] for p in self._pods if p.get("active")), None)
        if active:
            with contextlib.suppress(Exception):
                select.value = active

        # Seed paths from config sources if list is empty
        if not self.query("#paths-list").first(ListView).children:  # type: ignore[attr-defined]
            await self._seed_paths_from_config()

    async def _seed_paths_from_config(self) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            cfg = await client.get_config()
            paths = cfg.get("sources", {}).get("paths", [])
            for p in paths:
                await self._add_path_item(str(p))
        except Exception:  # noqa: BLE001
            pass

    async def _add_path_item(self, path: str) -> None:
        lst = self.query_one("#paths-list", ListView)
        await lst.append(ListItem(Label(path, markup=False), name=path))

    def _set_status(self, msg: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#ingest-status-line", Label).update(msg)

    def _selected_pod(self) -> str:
        with contextlib.suppress(Exception):
            val = self.query_one("#pod-select", Select).value
            if val and str(val) != Select.BLANK:
                return str(val)
        return "default"

    def _get_paths(self) -> list[str]:
        lst = self.query_one("#paths-list", ListView)
        paths = []
        for item in lst.children:
            name = getattr(item, "name", None)
            if name:
                paths.append(name)
        return paths

    def action_refresh_pods(self) -> None:
        self.run_worker(self._load_pods(), name="ingest-pod-load")

    def action_add_path(self) -> None:
        self._show_path_input()

    def action_remove_path(self) -> None:
        self.run_worker(self._remove_selected_path(), name="ingest-path-remove")

    def action_new_pod(self) -> None:
        self._toggle_new_pod_input()

    def on_key(self, event: events.Key) -> None:
        """Handle escape and enter for inline flow control."""
        if event.key == "escape":
            self._hide_path_input()
            inp = self.query_one("#new-pod-input", Input)
            inp.remove_class("visible")
            inp.value = ""
            event.stop()
        elif event.key == "enter":
            inp_row = self.query_one("#path-input-row", Static)
            new_pod_inp = self.query_one("#new-pod-input", Input)
            if "visible" not in inp_row.classes and "visible" not in new_pod_inp.classes:
                self.run_worker(self._do_ingest(), name="ingest-run")
                event.stop()

    def _show_path_input(self) -> None:
        row = self.query_one("#path-input-row", Static)
        row.add_class("visible")
        self.query_one("#path-input", Input).focus()

    def _hide_path_input(self) -> None:
        row = self.query_one("#path-input-row", Static)
        row.remove_class("visible")
        self.query_one("#path-input", Input).value = ""

    def _toggle_new_pod_input(self) -> None:
        inp = self.query_one("#new-pod-input", Input)
        if "visible" in inp.classes:
            inp.remove_class("visible")
            inp.value = ""
        else:
            inp.add_class("visible")
            inp.focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "path-input":
            path = event.value.strip()
            if path:
                await self._add_path_item(path)
            self._hide_path_input()
            event.stop()
        elif event.input.id == "new-pod-input":
            name = event.value.strip()
            if name:
                self.run_worker(self._create_pod(name), name="ingest-pod-create")
            inp = self.query_one("#new-pod-input", Input)
            inp.remove_class("visible")
            inp.value = ""
            event.stop()

    async def _remove_selected_path(self) -> None:
        lst = self.query_one("#paths-list", ListView)
        if lst.highlighted_child is not None:
            await lst.highlighted_child.remove()

    async def _create_pod(self, name: str) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            await client.create_pod(name)
            self._set_status(f"Created pod '{name}'")
            await self._load_pods()
            # Auto-select the new pod
            with contextlib.suppress(Exception):
                self.query_one("#pod-select", Select).value = name
        except PebbleClientError as exc:
            self._set_status(f"Error creating pod: {exc.detail}")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Error: {exc}")

    async def _do_ingest(self) -> None:
        paths = self._get_paths()
        pod = self._selected_pod()

        if not paths:
            self._set_status("No paths configured — press [a] to add paths")
            return

        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        self._set_status(f"Starting ingest into pod '{pod}'…")

        progress = self.query_one("#ingest-progress", IngestProgressBar)
        stream = client.ingest_stream()
        progress.start(stream)

        self.run_worker(
            client.ingest(paths if paths else None),
            name="ingest-post",
        )

    def on_ingest_complete(self, event: IngestComplete) -> None:
        pod = self._selected_pod()
        ts = _now_str()
        if event.success:
            self._set_status(f"[green]Ingest complete[/green] into '{pod}'")
            self._add_history(ts, pod, 0, 0, "OK")
            self.app.notify("Ingest complete", title="Ingest")  # type: ignore[attr-defined]
        else:
            self._set_status(f"[red]Ingest failed: {event.detail}[/red]")
            self._add_history(ts, pod, 0, 0, "ERR")
            self.app.notify(  # type: ignore[attr-defined]
                f"Ingest error: {event.detail}",
                title="Ingest",
                severity="error",
            )

    def _add_history(
        self, ts: str, pod: str, docs: int, chunks: int, status: str
    ) -> None:
        self._history.insert(0, (ts, pod, docs, chunks, status))
        self._history = self._history[:10]
        self._refresh_history()

    def _refresh_history(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.clear()
        for ts, pod, docs, chunks, status in self._history:
            table.add_row(ts, pod, str(docs), str(chunks), status)
