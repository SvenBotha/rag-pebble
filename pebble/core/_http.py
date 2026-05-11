"""Internal HTTP helper shared by the OpenAI embeddings and LLM clients.

One async function: `post_with_retry`. It performs the call, maps
status codes and httpx exceptions to Pebble's typed `ProviderError`
hierarchy, and retries transient failures (timeouts, 429, 5xx) with
exponential-backoff-with-jitter via tenacity.

Nothing else in the codebase imports tenacity. Keeping the retry policy
in one place means changing it is a one-file diff.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from pebble.core.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

DEFAULT_MAX_ATTEMPTS = 3


class _Retryable(ProviderError):
    """Internal marker. Translated into a public error class on final failure."""

    def __init__(self, public: ProviderError) -> None:
        super().__init__(str(public))
        self.public = public


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    json_body: dict[str, Any],
    timeout: float,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict[str, Any]:
    """POST `json_body` to `url`, return parsed JSON, retrying transient errors."""

    async def _once() -> dict[str, Any]:
        try:
            resp = await client.post(
                url, headers=headers, json=json_body, timeout=timeout
            )
        except httpx.TimeoutException as e:
            raise _Retryable(ProviderTimeoutError(f"timeout calling {url}: {e}")) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"transport error calling {url}: {e}") from e

        status = resp.status_code
        if 200 <= status < 300:
            return resp.json()  # type: ignore[no-any-return]
        body_snippet = resp.text[:200]
        if status == 401:
            raise ProviderAuthError(
                f"authentication failed at {url}: check API key ({body_snippet})"
            )
        if status == 429:
            raise _Retryable(
                ProviderRateLimitError(f"rate limited at {url}: {body_snippet}")
            )
        if 500 <= status < 600:
            raise _Retryable(
                ProviderError(f"server error {status} at {url}: {body_snippet}")
            )
        raise ProviderError(f"unexpected status {status} at {url}: {body_snippet}")

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential_jitter(initial=1.0, max=10.0),
            retry=retry_if_exception_type(_Retryable),
            reraise=True,
        ):
            with attempt:
                return await _once()
    except _Retryable as e:
        raise e.public from e
    raise AssertionError("unreachable: AsyncRetrying exited without returning")
