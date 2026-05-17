"""Splash screen shown at startup — press Enter or Space to continue."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen  # type: ignore[import-untyped]
from textual.widgets import Static

# Block-character logo — rendered with Unicode box-drawing + block elements.
_LOGO = """\
██████╗ ███████╗██████╗ ██████╗ ██╗     ███████╗
██╔══██╗██╔════╝██╔══██╗██╔══██╗██║     ██╔════╝
██████╔╝█████╗  ██████╔╝██████╔╝██║     █████╗
██╔═══╝ ██╔══╝  ██╔══██╗██╔══██╗██║     ██╔══╝
██║     ███████╗██████╔╝██████╔╝███████╗███████╗
╚═╝     ╚══════╝╚═════╝ ╚═════╝ ╚══════╝╚══════╝"""

_SUBTITLE = "RAG on a shoestring  ·  FAISS + SQLite, cloud LLMs"
_HINT = "Press  Enter  or  Space  to continue"


class SplashScreen(ModalScreen[None]):  # type: ignore[misc]
    """Full-screen splash that blocks until the user dismisses it."""

    DEFAULT_CSS = """
    SplashScreen {
        align: center middle;
        background: $background;
    }
    SplashScreen #splash-box {
        width: auto;
        height: auto;
        padding: 2 4;
        border: double $primary;
        background: $surface;
        align: center middle;
        layout: vertical;
    }
    SplashScreen #splash-logo {
        text-align: center;
        color: $primary;
        text-style: bold;
        padding: 0 0 1 0;
    }
    SplashScreen #splash-subtitle {
        text-align: center;
        color: $text-muted;
        padding: 0 0 1 0;
    }
    SplashScreen #splash-hint {
        text-align: center;
        color: $accent;
        text-style: italic;
    }
    """

    def compose(self) -> ComposeResult:
        with Static(id="splash-box"):
            yield Static(_LOGO, id="splash-logo", markup=False)
            yield Static(_SUBTITLE, id="splash-subtitle", markup=False)
            yield Static(_HINT, id="splash-hint", markup=False)

    def on_key(self, event: events.Key) -> None:
        if event.key in ("enter", "space"):
            self.dismiss()
