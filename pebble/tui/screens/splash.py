"""Splash screen shown at startup."""

from __future__ import annotations

import asyncio

import httpx
from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen  # type: ignore[import-untyped]
from textual.widgets import Label, Static

_LOGO = """\
██████╗ ███████╗██████╗ ██████╗ ██╗     ███████╗
██╔══██╗██╔════╝██╔══██╗██╔══██╗██║     ██╔════╝
██████╔╝█████╗  ██████╔╝██████╔╝██║     █████╗
██╔═══╝ ██╔══╝  ██╔══██╗██╔══██╗██║     ██╔══╝
██║     ███████╗██████╔╝██████╔╝███████╗███████╗
╚═╝     ╚══════╝╚═════╝ ╚═════╝ ╚══════╝╚══════╝"""

_SLOGAN = "Ask anything — your documents already know."
_VERSION = "v0.0.1"


class SplashScreen(ModalScreen[None]):  # type: ignore[misc]
    """Full-screen splash with health check. Auto-dismisses on connect."""

    def compose(self) -> ComposeResult:
        with Static(id="splash-box"):
            yield Static(_LOGO, id="splash-logo", markup=False)
            yield Static(_SLOGAN, id="splash-subtitle", markup=False)
            yield Static(_VERSION, id="splash-version", markup=False)
            yield Label("", id="splash-status")
            yield Label(
                "press  Enter  to continue",
                id="splash-hint",
                markup=False,
            )

    async def on_mount(self) -> None:
        self.run_worker(self._check_health(), name="splash-health")

    async def _check_health(self) -> None:
        from pebble.tui.client import PebbleClient

        status = self.query_one("#splash-status", Label)
        hint = self.query_one("#splash-hint", Label)

        status.update("[yellow]connecting…[/yellow]")
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            await client.health()
            status.update("[green]● connected[/green]")
            hint.update("press  Enter  to continue")
            await asyncio.sleep(5.0)
            self.dismiss()
        except (httpx.ConnectError, httpx.TimeoutException):
            status.update("[red]✗ offline — server not reachable[/red]")
            hint.update("press  Enter  to continue offline")
        except Exception:  # noqa: BLE001
            status.update("[yellow]? could not connect[/yellow]")
            hint.update("press  Enter  to continue")

    def on_key(self, event: events.Key) -> None:
        if event.key in ("enter", "space", "escape"):
            self.dismiss()
