"""Reusable confirmation modal."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen  # type: ignore[import-untyped]
from textual.widgets import Label, Static


class ConfirmScreen(ModalScreen[bool]):  # type: ignore[misc]
    """Ask the user to confirm a destructive action.

    Dismisses with True on Enter/y and False on Escape/n.
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Static(id="confirm-box"):
            yield Label(self._message, id="confirm-message", markup=False)
            yield Label(
                "[bold]Enter[/bold] / [bold]y[/bold]  confirm    "
                "[bold]Esc[/bold] / [bold]n[/bold]  cancel",
                id="confirm-keys",
            )

    def on_key(self, event: events.Key) -> None:
        if event.key in ("enter", "y"):
            self.dismiss(True)
            event.stop()
        elif event.key in ("escape", "n"):
            self.dismiss(False)
            event.stop()
