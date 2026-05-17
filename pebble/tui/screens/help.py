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
| `1` | Switch to Chat tab |
| `2` | Switch to Ingest tab |
| `3` | Switch to Documents tab |
| `4` | Switch to Pods tab |
| `5` | Switch to Config tab |
| `Tab` / `Shift+Tab` | Move between tabs |
| `Escape` | Close modal / discard |

## Chat tab
| Key | Action |
|-----|--------|
| `Enter` | Send query |
| `F2` | Toggle debug mode (show retrieved chunks) |
| `Ctrl+L` | Clear chat history |

## Ingest tab
| Key | Action |
|-----|--------|
| `Enter` | Start ingest |
| `a` | Add path to ingest list |
| `d` | Remove selected path |
| `n` | Create new pod (inline input) |
| `r` | Refresh pod list |

## Documents tab
| Key | Action |
|-----|--------|
| `d` | Delete selected document (with confirm) |
| `c` | Compact FAISS index |
| `r` | Refresh list |

## Pods tab
| Key | Action |
|-----|--------|
| `n` | Create new pod (inline input) |
| `d` | Delete selected pod (with confirm) |
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

    def compose(self) -> ComposeResult:
        with Static(id="help-box"):
            yield Markdown(_HELP_MD)

    def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "question_mark"):
            event.stop()
            self.dismiss()
