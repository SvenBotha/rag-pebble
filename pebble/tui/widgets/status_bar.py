"""Persistent status bar shown at the top of every screen."""

from __future__ import annotations

import math

import httpx
from textual.app import ComposeResult
from textual.widgets import Static

from pebble.tui.client import PebbleClient

_HELP_HINT = "  ?=help  1-5=tab  q=quit"


def _fmt_uptime(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _mem_estimate(chunks: int, dim: int = 1536) -> str:
    """Rough FAISS RAM estimate: n × dim × 4 bytes."""
    mb = (chunks * dim * 4) / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.1f}GB"
    return f"{mb:.0f}MB"


class StatusBar(Static):
    """Polls /health and /ready every 5 s; renders server state inline."""

    def compose(self) -> ComposeResult:
        yield Static("", id="status-info")
        yield Static(_HELP_HINT, id="status-hint", markup=False)

    def on_mount(self) -> None:
        self.set_interval(5, self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        self.run_worker(self._fetch(), exclusive=True, name="status-refresh")

    async def _fetch(self) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        info = self.query_one("#status-info", Static)
        try:
            health = await client.health()
            ready = await client.ready()
        except (httpx.ConnectError, httpx.TimeoutException):
            info.update("[red]✗ offline[/red]")
            return
        except Exception:  # noqa: BLE001
            info.update("[yellow]? error[/yellow]")
            return

        uptime = health.get("uptime_seconds", 0.0)
        if not isinstance(uptime, (int, float)):
            uptime = 0.0

        if ready.get("ready"):
            chunks = int(ready.get("index_size", 0) or 0)
            state = "[green]● ready[/green]"
        else:
            reason = ready.get("reason", "")
            chunks = 0
            if "loading" in (reason or ""):
                state = "[yellow]⟳ loading[/yellow]"
            else:
                state = "[red]✗ not ready[/red]"

        pod = "unknown"
        try:
            cfg = await client.get_config()
            pod = cfg.get("storage", {}).get("active_pod", "default")
        except Exception:  # noqa: BLE001
            pass

        n = math.floor(chunks)
        mem = _mem_estimate(n) if n > 0 else "0MB"
        info.update(
            f"[bold]{pod}[/bold]  "
            f"[dim]{n:,} chunks  ~{mem}[/dim]  "
            f"{state}  "
            f"[dim]up:{_fmt_uptime(uptime)}[/dim]"
        )
