"""Chat message widget — renders one query/answer pair."""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any

from textual.app import ComposeResult
from textual.widgets import Collapsible, Label, Markdown, Static


def _now() -> str:
    return datetime.now().strftime("%H:%M")


class MessageWidget(Static):
    """Renders a single query + answer exchange with styled cards."""

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
        self._ts = _now()
        self.add_class("assistant-msg")

    def compose(self) -> ComposeResult:
        yield Label(
            f"[dim]{self._ts}[/dim]  [bold]{self._query}[/bold]",
            classes="user-query",
        )
        yield Markdown(self._answer, classes="answer")

        sources = sorted({c["source_path"] for c in self._chunks})
        if sources:
            yield Label("[dim]sources:[/dim]", classes="source-header")
            for src in sources:
                yield Label(f"  {src}", classes="source", markup=False)

        if self._debug and self._chunks:
            with Collapsible(title=f"chunks ({len(self._chunks)})", collapsed=True):
                for c in self._chunks:
                    score = c.get("score", 0.0)
                    text = c.get("text", "")[:120]
                    yield Label(
                        f"[dim][{score:.3f}][/dim] {text}…",
                        classes="chunk-debug",
                    )


class LoadingMessage(Static):
    """Placeholder shown while a query is in flight."""

    def __init__(self, query: str) -> None:
        super().__init__()
        self._query = query
        self._ts = _now()
        self._dots = 0
        self._timer = None

    def compose(self) -> ComposeResult:
        yield Label(
            f"[dim]{self._ts}[/dim]  [bold]{self._query}[/bold]",
            classes="user-query",
        )
        yield Label("thinking", id="thinking-label", classes="thinking")

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.4, self._tick)

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        dots = "." * self._dots + " " * (3 - self._dots)
        with contextlib.suppress(Exception):
            self.query_one("#thinking-label", Label).update(f"thinking{dots}")

    async def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
