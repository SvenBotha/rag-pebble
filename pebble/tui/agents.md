# pebble/tui/ — Agent Context

Textual TUI for Pebble. **This module does not exist yet — it must be built.**

Add `textual >= 0.60` to `pyproject.toml` `dependencies` before starting.

## Architecture

The TUI calls the HTTP API for everything. It does not import `pebble.core` or `pebble.bootstrap` directly. This keeps the TUI decoupled: it works with any running Pebble server, local or remote.

The API URL defaults to `http://localhost:8000`, overridable via `PEBBLE_API_URL` env var or `--api-url` CLI flag.

## File structure to create

```
pebble/tui/
├── __init__.py
├── app.py              # PebbleApp(App) — main entry, tab bar, CSS
├── client.py           # async httpx client wrapper for all API calls
├── screens/
│   ├── __init__.py
│   ├── chat.py         # Chat screen
│   ├── documents.py    # Document management screen
│   ├── pods.py         # Pod management screen
│   └── config.py       # Config editor screen
└── widgets/
    ├── __init__.py
    ├── status_bar.py   # Persistent sidebar: pod name, chunk count, health
    ├── message.py      # Single chat message widget (query + answer + sources)
    └── progress.py     # Ingest progress bar fed by SSE
```

## `app.py` — PebbleApp

```python
from textual.app import App, ComposeResult
from textual.widgets import TabbedContent, TabPane

class PebbleApp(App):
    CSS_PATH = "app.tcss"

    def __init__(self, api_url: str = "http://localhost:8000"):
        super().__init__()
        self.api_url = api_url

    def compose(self) -> ComposeResult:
        yield StatusBar()
        with TabbedContent():
            with TabPane("Chat", id="chat"):
                yield ChatScreen()
            with TabPane("Documents", id="documents"):
                yield DocumentsScreen()
            with TabPane("Pods", id="pods"):
                yield PodsScreen()
            with TabPane("Config", id="config"):
                yield ConfigScreen()

    async def on_mount(self) -> None:
        # Start polling health/ready every 5s
        self.set_interval(5, self.refresh_status)
```

## `client.py` — API client

Centralise all HTTP calls here. Other widgets import from this module, not from `httpx` directly.

```python
import httpx
from pebble.api.models import QueryResponse, IngestResponse, ...

class PebbleClient:
    def __init__(self, base_url: str):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=120.0)

    async def query(self, query: str, top_k: int | None = None, debug: bool = False) -> QueryResponse: ...
    async def ingest(self, paths: list[str] | None = None) -> IngestResponse: ...
    async def list_documents(self) -> DocumentsResponse: ...
    async def delete_document(self, doc_id: str) -> DeleteResponse: ...
    async def compact(self) -> CompactResponse: ...
    async def list_pods(self) -> list[PodInfo]: ...
    async def create_pod(self, name: str) -> None: ...
    async def delete_pod(self, name: str) -> None: ...
    async def activate_pod(self, name: str) -> None: ...
    async def get_config(self) -> PebbleConfig: ...
    async def save_config(self, config: dict) -> None: ...
    async def reload_config(self) -> None: ...
    async def health(self) -> HealthResponse: ...
    async def ready(self) -> ReadyResponse: ...

    async def ingest_stream(self):
        """Async generator yielding IngestProgress events from SSE."""
        async with self._client.stream("GET", "/ingest/stream") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    yield json.loads(line[5:])

    async def aclose(self) -> None:
        await self._client.aclose()
```

## Screen specs

### Chat screen (`screens/chat.py`)
- Scrollable `ListView` of `MessageWidget` items
- Each `MessageWidget` shows: user query (right-aligned), answer text, source citations
- Debug mode (toggle with `d`): expands to show chunks with scores
- Bottom `Input` widget for new queries
- On submit: call `client.query(text, debug=debug_mode)`, append result to list, scroll to bottom
- While waiting: show spinner in message area

### Documents screen (`screens/documents.py`)
- `DataTable` with columns: Source Path, Chunks, Ingested At
- Keybindings: `d` = delete selected (confirm dialog), `r` = re-ingest selected
- Toolbar buttons: `Ingest Path` (opens path input dialog), `Compact`
- Ingest progress: show `ProgressBar` fed by SSE from `client.ingest_stream()`
- Refresh table after ingest completes

### Pods screen (`screens/pods.py`)
- `DataTable` with columns: Pod Name, Chunks, Size (MB), Active
- Active pod highlighted
- Keybindings: `n` = new pod (name input), `d` = delete (confirm), `Enter` = activate
- Activating a pod calls `POST /pods/{name}/activate` and shows a reminder that the server must restart to fully switch

### Config editor screen (`screens/config.py`)
- Sections collapsed by default, expandable
- For each config field: label, `Input` or `Select` widget, current value pre-filled
- On field change: check if it requires re-ingest (see `pebble/config/agents.md`) and show warning badge
- Save button: `POST /config` then `POST /admin/reload`
- Cancel button: restore all fields to current saved values

## Status bar widget (`widgets/status_bar.py`)
- Persistent on all screens (composed in `PebbleApp`, not in screens)
- Shows: `[pod: wikipedia]  [102,579 chunks]  [● ready]  [uptime: 2h 14m]`
- Polls `/health` and `/ready` every 5 seconds via `app.set_interval`
- If `/ready` returns 503: shows `[⟳ loading]`
- If server unreachable: shows `[✗ offline]`

## CSS
Create `pebble/tui/app.tcss` for Textual CSS. Keep it minimal — use Textual's built-in theme as the base.

## Testing the TUI
Textual provides `App.run_test()` for headless testing:

```python
async def test_chat_screen():
    async with PebbleApp(api_url="http://mock").run_test() as pilot:
        await pilot.click("#chat-input")
        await pilot.type("hello?")
        await pilot.press("enter")
        # assert answer appears
```

Add TUI tests to `tests/test_tui.py`. Mock `PebbleClient` to avoid network calls.
