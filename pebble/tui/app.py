"""PebbleApp — main Textual application entry point."""

from __future__ import annotations

import os

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import TabbedContent, TabPane

from pebble.tui.client import PebbleClient
from pebble.tui.screens.chat import ChatScreen
from pebble.tui.screens.config import ConfigScreen
from pebble.tui.screens.documents import DocumentsScreen
from pebble.tui.screens.help import HelpScreen
from pebble.tui.screens.pods import PodsScreen
from pebble.tui.screens.splash import SplashScreen
from pebble.tui.widgets.status_bar import StatusBar

DEFAULT_API_URL = "http://localhost:8000"


class PebbleApp(App[None]):
    """Pebble interactive TUI."""

    CSS_PATH = "app.tcss"
    THEME = "catppuccin-mocha"

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("question_mark", "show_help", "Help"),
    ]

    TITLE = "Pebble"

    def __init__(self, api_url: str | None = None) -> None:
        super().__init__()
        url = api_url or os.environ.get("PEBBLE_API_URL", DEFAULT_API_URL)
        self.client = PebbleClient(url)

    def compose(self) -> ComposeResult:
        yield StatusBar()
        with TabbedContent(initial="chat"):
            with TabPane("Chat", id="chat"):
                yield ChatScreen()
            with TabPane("Documents", id="documents"):
                yield DocumentsScreen()
            with TabPane("Pods", id="pods"):
                yield PodsScreen()
            with TabPane("Config", id="config"):
                yield ConfigScreen()

    async def on_mount(self) -> None:
        await self.push_screen(SplashScreen())

    async def action_show_help(self) -> None:
        await self.push_screen(HelpScreen())

    async def on_unmount(self) -> None:
        await self.client.aclose()
