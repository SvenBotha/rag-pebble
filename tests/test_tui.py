"""Headless TUI tests using Textual's App.run_test().

PebbleClient is replaced with MockClient so no running server is needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from pebble.tui.app import PebbleApp


class MockClient:
    """Canned responses for every PebbleClient method."""

    async def query(self, query: str, **kw: Any) -> dict[str, Any]:
        return {"answer": "mock answer", "chunks": []}

    async def ingest(self, paths: list[str] | None = None) -> dict[str, Any]:
        return {"ingested_documents": 1, "ingested_chunks": 5, "skipped": 0, "already_ingested": 0}

    async def ingest_stream(self) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "complete", "ingested_documents": 1, "ingested_chunks": 5, "skipped": 0}

    async def list_documents(self) -> dict[str, Any]:
        return {
            "documents": [
                {
                    "doc_id": "abc123",
                    "source_path": "./docs/readme.md",
                    "chunk_count": 5,
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
            "total": 1,
        }

    async def delete_document(self, doc_id: str) -> dict[str, Any]:
        return {"deleted_chunks": 5}

    async def compact(self) -> dict[str, Any]:
        return {"before": 10, "after": 5, "elapsed_seconds": 0.1}

    async def get_config(self) -> dict[str, Any]:
        return {
            "sources": {"paths": ["./docs"], "include": ["*.md"], "exclude": []},
            "chunking": {"method": "recursive", "chunk_size": 800, "overlap": 100},
            "embeddings": {
                "provider": "openai",
                "model": "text-embedding-3-small",
                "batch_size": 64,
            },
            "llm": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "temperature": 0.2,
                "max_tokens": 800,
            },
            "retrieval": {"mode": "vector", "top_k": 5, "similarity_threshold": 0.0},
            "storage": {"active_pod": "default", "pods_dir": "./data/pods"},
            "limits": {
                "max_document_mb": 25,
                "max_chunks_per_doc": 5000,
                "max_tokens_per_query": 4000,
                "max_embeddings_per_ingest": 50000,
                "concurrency": 4,
            },
            "debug": {"show_chunks": False, "show_scores": False, "log_prompts": False},
        }

    async def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return config

    async def reload_config(self) -> dict[str, Any]:
        return {"reloaded": True}

    async def list_pods(self) -> list[dict[str, Any]]:
        return [
            {"name": "default", "chunk_count": 42, "size_mb": 1.5, "active": True},
            {"name": "test", "chunk_count": 0, "size_mb": 0.0, "active": False},
        ]

    async def create_pod(self, name: str) -> dict[str, Any]:
        return {"name": name, "created": True}

    async def delete_pod(self, name: str) -> dict[str, Any]:
        return {"deleted_chunks": 0}

    async def activate_pod(self, name: str) -> dict[str, Any]:
        return {"message": f"active_pod set to '{name}'; restart required"}

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "uptime_seconds": 3661.0}

    async def ready(self) -> dict[str, Any]:
        return {"ready": True, "index_size": 42}

    async def aclose(self) -> None:
        pass


def _make_app() -> PebbleApp:
    app = PebbleApp(api_url="http://mock")
    app.client = MockClient()  # type: ignore[assignment]
    return app


async def _dismiss_splash(pilot: Any) -> None:
    """Helper: ensure splash is dismissed, either by auto-dismiss or by pressing Enter."""
    from pebble.tui.screens.splash import SplashScreen

    await pilot.pause(0.05)
    if isinstance(pilot.app.screen, SplashScreen):
        await pilot.press("enter")
        await pilot.pause(0.1)
    # Splash may have auto-dismissed — either way we're good


@pytest.mark.asyncio
async def test_splash_shown_on_start() -> None:
    """Splash screen is the first screen shown after mount."""
    from pebble.tui.screens.splash import SplashScreen

    async with _make_app().run_test() as pilot:
        await pilot.pause(0.05)
        assert isinstance(pilot.app.screen, SplashScreen)


@pytest.mark.asyncio
async def test_splash_dismisses_on_enter() -> None:
    """Pressing Enter on the splash returns to the main app."""
    from pebble.tui.screens.splash import SplashScreen
    from pebble.tui.widgets.status_bar import StatusBar

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        assert not isinstance(pilot.app.screen, SplashScreen)
        assert len(pilot.app.query(StatusBar)) == 1


@pytest.mark.asyncio
async def test_app_starts() -> None:
    """App mounts without raising; status bar is present after splash."""
    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        assert pilot.app.is_running
        status = pilot.app.query("StatusBar")
        assert len(status) == 1


@pytest.mark.asyncio
async def test_help_screen_opens_and_closes() -> None:
    """Pressing ? opens the help modal; pressing Escape closes it."""
    from pebble.tui.screens.help import HelpScreen

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        await pilot.press("question_mark")
        await pilot.pause(0.1)
        assert isinstance(pilot.app.screen, HelpScreen)

        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(pilot.app.screen, HelpScreen)


@pytest.mark.asyncio
async def test_help_screen_closes_on_question_mark() -> None:
    """Pressing ? again while help is open closes it (toggle)."""
    from pebble.tui.screens.help import HelpScreen

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        await pilot.press("question_mark")
        await pilot.pause(0.1)
        assert isinstance(pilot.app.screen, HelpScreen)

        await pilot.press("question_mark")
        await pilot.pause(0.1)
        assert not isinstance(pilot.app.screen, HelpScreen)


@pytest.mark.asyncio
async def test_chat_tab_visible() -> None:
    """Chat tab is the default and chat input is present."""
    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        from textual.widgets import Input

        inputs = pilot.app.query(Input)
        assert len(inputs) >= 1


@pytest.mark.asyncio
async def test_chat_submit_shows_answer() -> None:
    """Submitting a query appends a MessageWidget with the mock answer."""
    from textual.widgets import Input

    from pebble.tui.widgets.message import MessageWidget

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        inp = pilot.app.query_one("#chat-input", Input)
        inp.value = "hello?"
        await inp.action_submit()
        await pilot.pause(0.3)

        messages = pilot.app.query(MessageWidget)
        assert len(messages) >= 1


@pytest.mark.asyncio
async def test_documents_tab_loads() -> None:
    """Switching to Documents tab shows DataTable with correct columns."""
    from textual.widgets import DataTable, TabbedContent

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        tc = pilot.app.query_one(TabbedContent)
        tc.active = "documents"
        await pilot.pause(0.2)

        table = pilot.app.query_one("#doc-table", DataTable)
        col_labels = [str(c.label) for c in table.columns.values()]
        assert "Source Path" in col_labels
        assert "Chunks" in col_labels


@pytest.mark.asyncio
async def test_pods_tab_loads() -> None:
    """Pods tab shows DataTable with pod rows."""
    from textual.widgets import DataTable, TabbedContent

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        tc = pilot.app.query_one(TabbedContent)
        tc.active = "pods"
        await pilot.pause(0.2)

        table = pilot.app.query_one("#pod-table", DataTable)
        col_labels = [str(c.label) for c in table.columns.values()]
        assert "Pod Name" in col_labels
        assert "Active" in col_labels


@pytest.mark.asyncio
async def test_config_tab_loads() -> None:
    """Config tab renders collapsible sections."""
    from textual.widgets import Collapsible, TabbedContent

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        tc = pilot.app.query_one(TabbedContent)
        tc.active = "config"
        await pilot.pause(0.2)

        collapsibles = pilot.app.query(Collapsible)
        assert len(collapsibles) >= 3


@pytest.mark.asyncio
async def test_status_bar_shows_ready() -> None:
    """Status bar is present and has rendered content after a brief wait."""
    from textual.widgets import Static

    from pebble.tui.widgets.status_bar import StatusBar

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        await pilot.pause(0.2)

        bar = pilot.app.query_one(StatusBar)
        info = bar.query_one("#status-info", Static)
        text = str(info.render())
        assert len(text) > 0


@pytest.mark.asyncio
async def test_ingest_tab_loads() -> None:
    """Ingest tab shows pod selector and paths list."""
    from textual.widgets import Select, TabbedContent

    from pebble.tui.screens.ingest import IngestScreen

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        tc = pilot.app.query_one(TabbedContent)
        tc.active = "ingest"
        await pilot.pause(0.3)

        # IngestScreen is present
        assert len(pilot.app.query(IngestScreen)) == 1
        # Pod selector is present
        assert len(pilot.app.query(Select)) >= 1


@pytest.mark.asyncio
async def test_ingest_tab_has_five_tabs() -> None:
    """App now has five tabs: Chat, Ingest, Documents, Pods, Config."""
    from textual.widgets import TabPane

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        panes = pilot.app.query(TabPane)
        assert len(panes) == 5
        pane_ids = [p.id for p in panes]
        for expected in ("chat", "ingest", "documents", "pods", "config"):
            assert expected in pane_ids


@pytest.mark.asyncio
async def test_number_key_switches_to_ingest() -> None:
    """Pressing '2' switches to the Ingest tab."""
    from textual.widgets import TabbedContent

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        tc = pilot.app.query_one(TabbedContent)
        assert tc.active == "chat"

        await pilot.press("2")
        await pilot.pause(0.1)
        assert tc.active == "ingest"


@pytest.mark.asyncio
async def test_number_key_switches_tabs() -> None:
    """Number keys 1-5 switch to the expected tabs."""
    from textual.widgets import TabbedContent

    tab_map = {"1": "chat", "3": "documents", "4": "pods", "5": "config"}

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        tc = pilot.app.query_one(TabbedContent)

        for key, expected_id in tab_map.items():
            await pilot.press(key)
            await pilot.pause(0.05)
            assert tc.active == expected_id, f"key {key!r} should activate tab {expected_id!r}"


@pytest.mark.asyncio
async def test_ingest_tab_new_pod_input_appears() -> None:
    """Pressing 'n' in Ingest tab reveals the new pod input.

    Focus must be on a widget that doesn't capture single-char keys
    (e.g. ListView, not Select) for the shortcut to bubble up.
    """
    from textual.widgets import Input, ListView, TabbedContent

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        tc = pilot.app.query_one(TabbedContent)
        tc.active = "ingest"
        await pilot.pause(0.3)

        # Move focus to the paths list so 'n' bubbles up to IngestScreen
        lst = pilot.app.query_one("#paths-list", ListView)
        lst.focus()
        await pilot.pause(0.1)

        await pilot.press("n")
        await pilot.pause(0.1)

        new_pod_input = pilot.app.query_one("#new-pod-input", Input)
        assert "visible" in new_pod_input.classes


@pytest.mark.asyncio
async def test_documents_tab_has_no_ingest_key() -> None:
    """Documents tab no longer has ingest — 'i' key does nothing harmful."""
    from textual.widgets import TabbedContent

    from pebble.tui.screens.documents import DocumentsScreen

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        tc = pilot.app.query_one(TabbedContent)
        tc.active = "documents"
        await pilot.pause(0.2)

        # DocumentsScreen exists
        assert len(pilot.app.query(DocumentsScreen)) == 1
        # 'i' key no longer does anything (no crash)
        await pilot.press("i")
        await pilot.pause(0.1)
        # Still on documents tab, no modal opened
        assert tc.active == "documents"


@pytest.mark.asyncio
async def test_pods_inline_input_appears_on_n() -> None:
    """The 'new pod' action on PodsScreen shows the inline pod name input."""
    from textual.widgets import Static, TabbedContent

    from pebble.tui.screens.pods import PodsScreen

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        tc = pilot.app.query_one(TabbedContent)
        tc.active = "pods"
        await pilot.pause(0.2)

        # Trigger the action directly (DataTable captures single-char keys)
        pods_screen = pilot.app.query_one(PodsScreen)
        pods_screen.action_new_pod()
        await pilot.pause(0.1)

        inline = pilot.app.query_one("#pod-inline-input", Static)
        assert "visible" in inline.classes


@pytest.mark.asyncio
async def test_config_f2_does_not_save() -> None:
    """F2 no longer triggers save in Config tab (F2 belongs to Chat debug toggle)."""
    from textual.widgets import TabbedContent

    async with _make_app().run_test() as pilot:
        await _dismiss_splash(pilot)
        tc = pilot.app.query_one(TabbedContent)
        tc.active = "config"
        await pilot.pause(0.2)

        # Check the config status before pressing F2
        from textual.widgets import Static

        status = pilot.app.query_one("#config-status", Static)
        # Status should say "Config loaded" after load
        await pilot.pause(0.1)
        initial_text = str(status.render())

        # F2 should NOT trigger save (should be a no-op or pass through)
        await pilot.press("f2")
        await pilot.pause(0.1)

        # Status should NOT say "Saving…" or "Saved and reloaded"
        after_text = str(status.render())
        assert "Saving" not in after_text
        assert "Saved" not in after_text or initial_text == after_text
