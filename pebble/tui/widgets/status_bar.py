"""Persistent status bar shown at the top of every screen."""

from __future__ import annotations

import math

import httpx
from textual.app import ComposeResult
from textual.widgets import Static

from pebble.tui.client import PebbleClient

_HELP_HINT = "  ?=help  q=quit"


def _fmt_uptime(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


class StatusBar(Static):
    """Polls /health and /ready every 5 s; renders server state inline."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        layout: horizontal;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    StatusBar #status-info {
        width: 1fr;
        height: 1;
    }
    StatusBar #status-hint {
        width: auto;
        height: 1;
        color: $text-muted;
        text-style: dim;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="status-info", markup=False)
        yield Static(_HELP_HINT, id="status-hint", markup=False)

    def on_mount(self) -> None:
        self.set_interval(5, self._refresh)
        self._refresh()

    # Override update() so callers (e.g. _fetch) route text to the inner widget.
    def update(self, content: str = "") -> None:  # type: ignore[override]
        try:
            self.query_one("#status-info", Static).update(content)
        except Exception:  # noqa: BLE001
            super().update(content)

    def _refresh(self) -> None:
        self.run_worker(self._fetch(), exclusive=True, name="status-refresh")

    async def _fetch(self) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            health = await client.health()
            ready = await client.ready()
        except (httpx.ConnectError, httpx.TimeoutException):
            self.update("✗ offline")  # type: ignore[arg-type]
            return
        except Exception:  # noqa: BLE001
            self.update("? error")  # type: ignore[arg-type]
            return

        uptime = health.get("uptime_seconds", 0.0)
        if not isinstance(uptime, (int, float)):
            uptime = 0.0

        if ready.get("ready"):
            chunks = ready.get("index_size", 0)
            state = "● ready"
        else:
            reason = ready.get("reason", "")
            chunks = 0
            state = "⟳ loading" if "loading" in (reason or "") else "✗ not ready"

        pod = "unknown"
        try:
            cfg = await client.get_config()
            pod = cfg.get("storage", {}).get("active_pod", "default")
        except Exception:  # noqa: BLE001
            pass

        n = math.floor(chunks)
        self.update(f"pod:{pod}  {n:,} chunks  {state}  up:{_fmt_uptime(uptime)}")
