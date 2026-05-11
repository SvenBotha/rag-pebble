"""Cloud embedding providers."""

from __future__ import annotations

import os
from collections.abc import Sequence

import httpx

from pebble.core._http import post_with_retry
from pebble.core.budgets import enforce_ingest_budget
from pebble.core.errors import ConfigError, ProviderError

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
EMBED_TIMEOUT_S = 30.0

_OPENAI_EMBED_DIMS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbedder:
    """OpenAI embeddings client.

    Batches `texts` into requests of size `batch_size`. Budget is enforced
    against the *total* number of texts in a single call (typical ingest
    pattern: one call per document with all of that document's chunks)
    before any HTTP work.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        model: str,
        batch_size: int,
        max_embeddings_per_ingest: int,
        api_key: str | None = None,
    ) -> None:
        if model not in _OPENAI_EMBED_DIMS:
            raise ConfigError(
                f"unknown OpenAI embedding model {model!r}; "
                f"known: {sorted(_OPENAI_EMBED_DIMS)}"
            )
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ConfigError("OPENAI_API_KEY is not set")
        self._client = client
        self._model = model
        self._batch_size = batch_size
        self._max_per_ingest = max_embeddings_per_ingest
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    @property
    def dim(self) -> int:
        return _OPENAI_EMBED_DIMS[self._model]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        enforce_ingest_budget(num_chunks=len(texts), limit=self._max_per_ingest)

        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            payload = await post_with_retry(
                self._client,
                OPENAI_EMBEDDINGS_URL,
                headers=self._headers,
                json_body={"model": self._model, "input": list(batch)},
                timeout=EMBED_TIMEOUT_S,
            )
            data = payload.get("data")
            if not isinstance(data, list) or len(data) != len(batch):
                got = len(data) if isinstance(data, list) else "non-list"
                raise ProviderError(
                    f"unexpected embeddings response shape (got {got}, expected {len(batch)})"
                )
            for item in data:
                vec = item.get("embedding")
                if not isinstance(vec, list):
                    raise ProviderError("embedding entry missing 'embedding' list")
                out.append([float(x) for x in vec])
        return out
