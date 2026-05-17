"""Help modal — shows all keyboard shortcuts, dismisses on Escape or ?."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen  # type: ignore[import-untyped]
from textual.widgets import Markdown, Static

_HELP_MD = """\
# Pebble — Keyboard Shortcuts

## Global
| Key | Action |
|-----|--------|
| `q` | Quit |
| `?` | Toggle this help page |
| `Tab` / `Shift+Tab` | Switch between tabs |
| `Escape` | Close modal / discard |

## Chat tab
| Key | Action |
|-----|--------|
| `Enter` | Send query |
| `F2` | Toggle debug mode (show retrieved chunks) |

## Documents tab
| Key | Action |
|-----|--------|
| `i` | Ingest new path(s) |
| `d` | Delete selected document |
| `c` | Compact FAISS index |
| `r` | Refresh list |

## Pods tab
| Key | Action |
|-----|--------|
| `n` | Create new pod |
| `d` | Delete selected pod |
| `a` / `Enter` | Activate selected pod |
| `r` | Refresh list |

## Config tab
| Key | Action |
|-----|--------|
| `Ctrl+S` | Save and reload config |
| `Escape` | Discard changes |

---

*After switching active pod or changing storage settings, restart the server.*
"""


class HelpScreen(ModalScreen[None]):  # type: ignore[misc]
    """Keyboard shortcut reference — press Escape or ? to close."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
        background: $background 70%;
    }
    HelpScreen #help-box {
        width: 70;
        height: auto;
        max-height: 90vh;
        border: round $primary;
        background: $surface;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    def compose(self) -> ComposeResult:
        with Static(id="help-box"):
            yield Markdown(_HELP_MD)

    def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "question_mark"):
            event.stop()  # prevent ? from re-triggering app's show_help binding
            self.dismiss()
