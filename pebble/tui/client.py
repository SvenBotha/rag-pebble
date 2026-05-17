"""Async HTTP client for the Pebble API.

All TUI screens import from here, never from httpx directly. This keeps
every API call in one place and makes testing easy: swap PebbleClient for
a mock and nothing else changes.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class PebbleClientError(Exception):
    """Raised when the API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class PebbleClient:
    """Thin async wrapper around every Pebble HTTP endpoint."""

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=120.0)

    # ------------------------------------------------------------------ helpers

    def _raise(self, resp: httpx.Response) -> None:
        if resp.is_error:
            try:
                detail = resp.json().get("detail", resp.text[:200])
            except Exception:  # noqa: BLE001
                detail = resp.text[:200]
            raise PebbleClientError(resp.status_code, detail)

    async def _get(self, path: str) -> dict[str, Any]:
        resp = await self._client.get(path)
        self._raise(resp)
        return resp.json()  # type: ignore[no-any-return]

    async def _post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = await self._client.post(path, **kwargs)
        self._raise(resp)
        return resp.json()  # type: ignore[no-any-return]

    async def _delete(self, path: str) -> dict[str, Any]:
        resp = await self._client.delete(path)
        self._raise(resp)
        return resp.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------ query

    async def query(
        self,
        query: str,
        *,
        top_k: int | None = None,
        debug: bool = False,
    ) -> dict[str, Any]:
        return await self._post(
            "/query",
            json={"query": query, "top_k": top_k, "debug": debug},
        )

    # ------------------------------------------------------------------ ingest

    async def ingest(self, paths: list[str] | None = None) -> dict[str, Any]:
        return await self._post("/ingest", json={"paths": paths})

    async def ingest_stream(self) -> AsyncIterator[dict[str, Any]]:
        """Async generator yielding SSE events from GET /ingest/stream.

        Connect *before* triggering POST /ingest so the queue exists
        when the ingest starts writing to it.
        """
        async with self._client.stream("GET", "/ingest/stream") as resp:
            self._raise(resp)
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    yield json.loads(line[5:].strip())

    # ------------------------------------------------------------------ documents

    async def list_documents(self) -> dict[str, Any]:
        return await self._get("/documents")

    async def delete_document(self, doc_id: str) -> dict[str, Any]:
        return await self._delete(f"/documents/{doc_id}")

    async def compact(self) -> dict[str, Any]:
        return await self._post("/admin/compact")

    # ------------------------------------------------------------------ config

    async def get_config(self) -> dict[str, Any]:
        resp = await self._get("/config")
        inner = resp.get("config", resp)
        return inner if isinstance(inner, dict) else resp

    async def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        resp = await self._post("/config", json=config)
        inner = resp.get("config", resp)
        return inner if isinstance(inner, dict) else resp

    async def reload_config(self) -> dict[str, Any]:
        return await self._post("/admin/reload")

    # ------------------------------------------------------------------ pods

    async def list_pods(self) -> list[dict[str, Any]]:
        result = await self._get("/pods")
        return result  # type: ignore[return-value]

    async def create_pod(self, name: str) -> dict[str, Any]:
        return await self._post("/pods", json={"name": name})

    async def delete_pod(self, name: str) -> dict[str, Any]:
        return await self._delete(f"/pods/{name}")

    async def activate_pod(self, name: str) -> dict[str, Any]:
        return await self._post(f"/pods/{name}/activate")

    # ------------------------------------------------------------------ health

    async def health(self) -> dict[str, Any]:
        return await self._get("/health")

    async def ready(self) -> dict[str, Any]:
        return await self._get("/ready")

    # ------------------------------------------------------------------ lifecycle

    async def aclose(self) -> None:
        await self._client.aclose()
