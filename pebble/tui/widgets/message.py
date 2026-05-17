"""Chat message widget — renders one query/answer pair."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.widgets import Label, Markdown, Static


class MessageWidget(Static):
    """Renders a single query + answer exchange."""

    DEFAULT_CSS = """
    MessageWidget {
        margin: 0 0 1 0;
        padding: 0 1;
        height: auto;
    }
    MessageWidget .user-query {
        text-align: right;
        color: $accent;
        margin-bottom: 0;
    }
    MessageWidget .answer {
        height: auto;
        margin: 0 0 0 2;
        padding: 0;
    }
    MessageWidget .source {
        color: $text-muted;
        margin: 0 0 0 2;
    }
    MessageWidget .chunk-debug {
        color: $text-muted;
        margin: 0 0 0 4;
    }
    """

    def __init__(
        self,
        query: str,
        answer: str,
        chunks: list[dict[str, Any]] | None = None,
        debug: bool = False,
    ) -> None:
        super().__init__()
        self._query = query
        self._answer = answer
        self._chunks = chunks or []
        self._debug = debug

    def compose(self) -> ComposeResult:
        yield Label(f"> {self._query}", classes="user-query")
        yield Markdown(self._answer, classes="answer")
        sources = {c["source_path"] for c in self._chunks}
        for src in sources:
            yield Label(f"source: {src}", classes="source", markup=False)
        if self._debug:
            for c in self._chunks:
                score = c.get("score", 0.0)
                text = c.get("text", "")[:120]
                yield Label(f"  [{score:.3f}] {text}…", classes="chunk-debug", markup=False)


class LoadingMessage(Static):
    """Placeholder shown while a query is in flight."""

    DEFAULT_CSS = """
    LoadingMessage {
        margin: 0 0 1 0;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, query: str) -> None:
        super().__init__()
        self._query = query

    def compose(self) -> ComposeResult:
        yield Label(f"> {self._query}", classes="user-query")
        yield Label("…thinking…", classes="answer")
