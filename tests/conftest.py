"""Shared test fixtures and stub providers.

Tests never hit the real OpenAI API. The stubs here return deterministic
vectors and canned LLM responses so tests stay fast and offline.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import pytest

STUB_DIM = 16


class StubEmbedder:
    """Deterministic, hash-derived 16-dim embeddings.

    Same text → same vector. Different text → different vector (collisions
    are theoretically possible but won't matter for our tests).
    """

    def __init__(self, dim: int = STUB_DIM) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vec = [
                ((digest[i % len(digest)] / 255.0) - 0.5)
                for i in range(self._dim)
            ]
            out.append(vec)
        return out


class StubLLM:
    """Returns a canned answer that echoes the query, plus a synthetic citation."""

    def __init__(self, canned: str = "stub answer") -> None:
        self._canned = canned

    async def complete(
        self,
        prompt: str,
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        return f"{self._canned} (received {len(prompt)} chars of context)"


@pytest.fixture
def tmp_store_paths(tmp_path: Path) -> tuple[Path, Path]:
    """Yields (index_path, metadata_path) under a per-test temp directory."""
    return tmp_path / "test.index", tmp_path / "test.meta.sqlite"


@pytest.fixture
def stub_embedder() -> StubEmbedder:
    return StubEmbedder()


@pytest.fixture
def stub_llm() -> StubLLM:
    return StubLLM()
