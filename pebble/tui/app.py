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
from pebble.tui.screens.ingest import IngestScreen
from pebble.tui.screens.pods import PodsScreen
from pebble.tui.screens.splash import SplashScreen
from pebble.tui.widgets.status_bar import StatusBar

DEFAULT_API_URL = "http://localhost:8000"

# Tab IDs in order — used by number-key bindings
_TABS = ["chat", "ingest", "documents", "pods", "config"]


class PebbleApp(App[None]):
    """Pebble interactive TUI."""

    CSS_PATH = "app.tcss"
    THEME = "tokyo-night"

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("question_mark", "show_help", "Help"),
        Binding("1", "switch_tab('chat')", "Chat", show=False),
        Binding("2", "switch_tab('ingest')", "Ingest", show=False),
        Binding("3", "switch_tab('documents')", "Docs", show=False),
        Binding("4", "switch_tab('pods')", "Pods", show=False),
        Binding("5", "switch_tab('config')", "Config", show=False),
    ]

    TITLE = "Pebble"
    SUB_TITLE = "RAG on a shoestring"

    def __init__(self, api_url: str | None = None) -> None:
        super().__init__()
        url = api_url or os.environ.get("PEBBLE_API_URL", DEFAULT_API_URL)
        self.client = PebbleClient(url)

    def compose(self) -> ComposeResult:
        yield StatusBar()
        with TabbedContent(initial="chat"):
            with TabPane("Chat", id="chat"):
                yield ChatScreen()
            with TabPane("Ingest", id="ingest"):
                yield IngestScreen()
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

    def action_switch_tab(self, tab_id: str) -> None:
        tc = self.query_one(TabbedContent)
        tc.active = tab_id

    async def on_unmount(self) -> None:
        await self.client.aclose()
