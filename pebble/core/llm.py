"""Cloud LLM providers."""

from __future__ import annotations

import os

import httpx

from pebble.core._http import post_with_retry
from pebble.core.budgets import enforce_query_budget
from pebble.core.errors import ConfigError, ProviderError

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
LLM_TIMEOUT_S = 60.0


class OpenAILLM:
    """OpenAI chat-completions client.

    `complete` enforces `max_tokens_per_query` against the estimated
    input plus the requested `max_tokens` *before* the HTTP call. The
    estimator is a `chars/4` heuristic (see `pebble.core.budgets`) and
    is conservative by design.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        model: str,
        max_tokens_per_query: int,
        api_key: str | None = None,
    ) -> None:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ConfigError("OPENAI_API_KEY is not set")
        self._client = client
        self._model = model
        self._max_tokens_per_query = max_tokens_per_query
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    async def complete(
        self,
        prompt: str,
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        enforce_query_budget(
            system=system,
            user=prompt,
            max_output_tokens=max_tokens,
            limit=self._max_tokens_per_query,
        )

        payload = await post_with_retry(
            self._client,
            OPENAI_CHAT_URL,
            headers=self._headers,
            json_body={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=LLM_TIMEOUT_S,
        )

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("chat-completions response missing 'choices'")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ProviderError("chat-completions choice missing 'message'")
        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderError("chat-completions message has no string 'content'")
        return content
