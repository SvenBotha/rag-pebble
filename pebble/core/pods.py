"""Pod management helpers.

A pod is an independent FAISS index + SQLite store under a named subdirectory
of `pods_dir`. This module provides pure-sync helpers to list, create, and
delete pods without touching the store or bootstrap layers.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pebble.core.errors import StoreError

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")

_INDEX_FILENAME = "pebble.index"
_META_FILENAME = "pebble.meta.sqlite"


def _validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise StoreError(
            f"invalid pod name {name!r}: must match ^[a-zA-Z0-9][a-zA-Z0-9_-]{{0,63}}$"
        )


@dataclass(frozen=True)
class PodInfo:
    name: str
    chunk_count: int
    size_mb: float
    active: bool


def _read_live_count(meta_path: Path) -> int:
    if not meta_path.exists():
        return 0
    try:
        conn = sqlite3.connect(str(meta_path), check_same_thread=False)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM chunks WHERE deleted = 0")
            return int(cur.fetchone()[0])
        except sqlite3.OperationalError:
            return 0
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return 0


def _dir_size_mb(directory: Path) -> float:
    total = sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 3)


def list_pods(pods_dir: Path, active_pod: str) -> list[PodInfo]:
    """Return info for every subdirectory of `pods_dir`, sorted by name."""
    if not pods_dir.exists():
        return []
    pods: list[PodInfo] = []
    for entry in sorted(pods_dir.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / _META_FILENAME
        pods.append(
            PodInfo(
                name=entry.name,
                chunk_count=_read_live_count(meta_path),
                size_mb=_dir_size_mb(entry),
                active=(entry.name == active_pod),
            )
        )
    return pods


def create_pod(pods_dir: Path, name: str) -> None:
    """Create a new empty pod directory.

    Raises `StoreError` if the name is invalid or the pod already exists.
    """
    _validate_name(name)
    pod_dir = pods_dir / name
    if pod_dir.exists():
        raise StoreError(f"pod {name!r} already exists")
    pod_dir.mkdir(parents=True, exist_ok=False)


def delete_pod(pods_dir: Path, name: str) -> None:
    """Remove a pod directory and all its contents.

    Raises `StoreError` if the pod does not exist.
    """
    _validate_name(name)
    pod_dir = pods_dir / name
    if not pod_dir.exists():
        raise StoreError(f"pod {name!r} does not exist")
    shutil.rmtree(pod_dir)


def write_active_pod(config_path: Path | None, pod_name: str) -> None:
    """Persist `active_pod` in the config YAML file.

    If `config_path` is None the operation is a no-op (caller should
    tell the user to set the pod manually). When the file exists, its
    full contents are preserved and only `storage.active_pod` is updated.
    """
    _validate_name(pod_name)
    if config_path is None or not config_path.is_file():
        return

    raw: dict[str, Any] = {}
    with config_path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
        if isinstance(loaded, dict):
            raw = loaded

    storage: dict[str, Any] = raw.setdefault("storage", {})
    storage["active_pod"] = pod_name
    # Remove deprecated fields if present so they don't override the pod path.
    storage.pop("index_path", None)
    storage.pop("metadata_path", None)

    with config_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(raw, fh, default_flow_style=False, allow_unicode=True)
