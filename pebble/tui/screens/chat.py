"""Chat screen — scrollable history of query/answer pairs."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalScroll  # type: ignore[import-untyped]
from textual.widgets import Input, Label, Static

from pebble.tui.client import PebbleClient, PebbleClientError
from pebble.tui.widgets.message import LoadingMessage, MessageWidget


class ChatScreen(Static):
    """Main chat interface: history scroll + input box at the bottom."""

    DEFAULT_CSS = """
    ChatScreen {
        height: 1fr;
        layout: vertical;
    }
    ChatScreen #history {
        height: 1fr;
    }
    ChatScreen #chat-hint {
        height: 1;
        color: $text-muted;
        padding: 0 1;
        dock: bottom;
    }
    ChatScreen #chat-input {
        height: 3;
        dock: bottom;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._debug = False

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="history")
        yield Label("F2 = debug  |  Enter = send", id="chat-hint")
        yield Input(placeholder="Type your question…", id="chat-input")

    def on_key(self, event: events.Key) -> None:
        """F2 toggles debug mode; Enter is handled by the Input widget directly."""
        if event.key == "f2":
            self._toggle_debug()
            event.stop()

    def _toggle_debug(self) -> None:
        self._debug = not self._debug
        hint = (
            "F2 = debug [ON]  |  Enter = send"
            if self._debug
            else "F2 = debug  |  Enter = send"
        )
        self.query_one("#chat-hint", Label).update(hint)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return

        inp = self.query_one("#chat-input", Input)
        inp.value = ""
        inp.disabled = True

        history = self.query_one("#history", VerticalScroll)
        placeholder = LoadingMessage(query)
        await history.mount(placeholder)
        history.scroll_end(animate=False)

        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            result = await client.query(query, debug=self._debug)
        except PebbleClientError as exc:
            answer = f"[error] {exc.detail}"
            chunks: list[dict] = []
        except Exception as exc:  # noqa: BLE001
            answer = f"[error] {exc}"
            chunks = []
        else:
            answer = result.get("answer", "")
            chunks = result.get("chunks", [])

        await placeholder.remove()
        msg = MessageWidget(query, answer, chunks=chunks, debug=self._debug)
        await history.mount(msg)
        history.scroll_end(animate=False)
        inp.disabled = False
        inp.focus()
