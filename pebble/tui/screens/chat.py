"""Chat screen — scrollable history of query/answer pairs."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalScroll  # type: ignore[import-untyped]
from textual.widgets import Input, Label, Static

from pebble.tui.client import PebbleClient, PebbleClientError
from pebble.tui.widgets.message import LoadingMessage, MessageWidget

_HINT_NORMAL = "F2=debug  Ctrl+L=clear  Enter=send"
_HINT_DEBUG = "F2=debug[ON]  Ctrl+L=clear  Enter=send"


class ChatScreen(Static):
    """Main chat interface: history scroll + input box at the bottom."""

    def __init__(self) -> None:
        super().__init__()
        self._debug = False

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="history")
        with Static(id="chat-input-wrapper"):
            yield Label(_HINT_NORMAL, id="chat-hint", markup=False)
            yield Input(placeholder="Ask anything…", id="chat-input")

    def on_key(self, event: events.Key) -> None:
        if event.key == "f2":
            self._toggle_debug()
            event.stop()
        elif event.key == "ctrl+l":
            self._clear_history()
            event.stop()

    def _toggle_debug(self) -> None:
        self._debug = not self._debug
        hint = _HINT_DEBUG if self._debug else _HINT_NORMAL
        self.query_one("#chat-hint", Label).update(hint)

    def _clear_history(self) -> None:
        history = self.query_one("#history", VerticalScroll)
        history.remove_children()

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
            answer = f"**Error:** {exc.detail}"
            chunks: list[dict] = []
        except Exception as exc:  # noqa: BLE001
            answer = f"**Error:** {exc}"
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
