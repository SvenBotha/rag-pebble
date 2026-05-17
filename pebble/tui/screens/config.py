"""Config editor screen — form-based editor for config.yaml fields."""

from __future__ import annotations

import contextlib
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.widgets import Collapsible, Input, Label, Select, Static

from pebble.tui.client import PebbleClient, PebbleClientError

# Fields that need attention when changed
_REINGEST_FIELDS = {"embeddings.model", "chunking.chunk_size", "chunking.overlap"}
_RESTART_FIELDS = {"storage.active_pod"}

# (section, field, label, widget_type, choices_if_select)
_FIELDS: list[tuple[str, str, str, str, list[str]]] = [
    # sources
    ("sources", "paths", "Source paths (comma-sep)", "input", []),
    # chunking
    ("chunking", "method", "Method", "select", ["recursive"]),
    ("chunking", "chunk_size", "Chunk size", "input", []),
    ("chunking", "overlap", "Overlap", "input", []),
    # embeddings
    ("embeddings", "provider", "Provider", "select", ["openai"]),
    ("embeddings", "model", "Model", "input", []),
    ("embeddings", "batch_size", "Batch size", "input", []),
    # llm
    ("llm", "provider", "Provider", "select", ["openai"]),
    ("llm", "model", "Model", "input", []),
    ("llm", "temperature", "Temperature", "input", []),
    ("llm", "max_tokens", "Max tokens", "input", []),
    # retrieval
    ("retrieval", "mode", "Mode", "select", ["vector", "hybrid", "graph"]),
    ("retrieval", "top_k", "Top k", "input", []),
    ("retrieval", "similarity_threshold", "Similarity threshold", "input", []),
    # storage
    ("storage", "active_pod", "Active pod", "input", []),
    # limits
    ("limits", "max_document_mb", "Max document MB", "input", []),
    ("limits", "max_chunks_per_doc", "Max chunks per doc", "input", []),
    ("limits", "max_tokens_per_query", "Max tokens per query", "input", []),
    ("limits", "max_embeddings_per_ingest", "Max embeddings per ingest", "input", []),
    # debug
    ("debug", "show_chunks", "Show chunks", "select", ["false", "true"]),
    ("debug", "show_scores", "Show scores", "select", ["false", "true"]),
    ("debug", "log_prompts", "Log prompts", "select", ["false", "true"]),
]


def _field_id(section: str, field: str) -> str:
    return f"cfg-{section}-{field}"


def _val_str(v: Any) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v)


class ConfigScreen(Static):
    """Form-based config editor grouped into collapsible sections."""

    def __init__(self) -> None:
        super().__init__()
        self._original: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        sections: dict[str, list[tuple[str, str, str, str, list[str]]]] = {}
        for entry in _FIELDS:
            section = entry[0]
            sections.setdefault(section, []).append(entry)

        for section, fields in sections.items():
            with Collapsible(title=section.capitalize(), collapsed=True, id=f"sec-{section}"):
                for _, field, label, wtype, choices in fields:
                    fid = _field_id(section, field)
                    key = f"{section}.{field}"
                    badge = ""
                    badge_cls = ""
                    if key in _REINGEST_FIELDS:
                        badge = " ⚠ re-ingest required"
                        badge_cls = "warning-badge"
                    elif key in _RESTART_FIELDS:
                        badge = " ⚠ restart required"
                        badge_cls = "restart-badge"
                    yield Label(f"{label}{badge}", classes=badge_cls if badge else "")
                    if wtype == "select":
                        opts = [(c, c) for c in choices]
                        yield Select(opts, id=fid, allow_blank=False)
                    else:
                        yield Input(value="", id=fid)

        yield Static(id="config-status", classes="status-line")
        yield Static(
            "Ctrl+S = save  |  Esc = cancel",
            id="config-toolbar",
            markup=False,
        )

    def on_mount(self) -> None:
        self.run_worker(self._load(), name="config-load")

    async def _load(self) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        try:
            cfg = await client.get_config()
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Error loading config: {exc}")
            return
        self._original = cfg
        self._populate(cfg)
        self._set_status("Config loaded")

    def _populate(self, cfg: dict[str, Any]) -> None:
        for section, field, _label, wtype, _choices in _FIELDS:
            section_data = cfg.get(section, {})
            raw = section_data.get(field, "")
            fid = _field_id(section, field)
            val = _val_str(raw)
            try:
                if wtype == "select":
                    widget = self.query_one(f"#{fid}", Select)
                    widget.value = val
                else:
                    widget2 = self.query_one(f"#{fid}", Input)
                    widget2.value = val
            except Exception:  # noqa: BLE001
                pass

    def _collect(self) -> dict[str, Any]:
        result: dict[str, dict[str, Any]] = {}
        for section, field, _label, wtype, _choices in _FIELDS:
            fid = _field_id(section, field)
            try:
                if wtype == "select":
                    val: Any = str(self.query_one(f"#{fid}", Select).value)
                else:
                    val = self.query_one(f"#{fid}", Input).value
            except Exception:  # noqa: BLE001
                continue
            # Coerce booleans
            if val in ("true", "True"):
                val = True
            elif val in ("false", "False"):
                val = False
            # Coerce numbers where the original was numeric
            orig_val = self._original.get(section, {}).get(field)
            if isinstance(orig_val, int) and not isinstance(orig_val, bool):
                with contextlib.suppress(ValueError, TypeError):
                    val = int(val)
            elif isinstance(orig_val, float):
                with contextlib.suppress(ValueError, TypeError):
                    val = float(val)
            elif isinstance(orig_val, list):
                val = [v.strip() for v in str(val).split(",") if v.strip()]
            result.setdefault(section, {})[field] = val
        return result

    def _set_status(self, msg: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#config-status", Static).update(msg)

    def on_key(self, event: events.Key) -> None:
        """s = save, Escape = cancel — fired via bubble from focused inputs."""
        if event.key == "ctrl+s" or event.key == "f2":
            self.run_worker(self._do_save(), name="config-save")
            event.stop()
        elif event.key == "escape":
            self._do_cancel()
            event.stop()

    async def _do_save(self) -> None:
        client: PebbleClient = self.app.client  # type: ignore[attr-defined]
        self._set_status("Saving…")
        payload = self._collect()
        try:
            await client.save_config(payload)
            await client.reload_config()
            self._set_status("Saved and reloaded")
            cfg = await client.get_config()
            self._original = cfg
        except PebbleClientError as exc:
            self._set_status(f"Save error: {exc.detail}")

    def _do_cancel(self) -> None:
        self._populate(self._original)
        self._set_status("Changes discarded")
