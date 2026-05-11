"""Typed exceptions raised across Pebble's subsystems.

Concrete provider implementations translate their library-specific errors
(httpx timeouts, openai.RateLimitError, etc.) into these types so the API
and CLI layers handle exactly one taxonomy.
"""

from __future__ import annotations


class PebbleError(Exception):
    """Base class for all Pebble-raised exceptions."""


class ConfigError(PebbleError):
    """Configuration is missing, malformed, or refers to absent env vars."""


class ProviderError(PebbleError):
    """A cloud provider call failed in a way the caller may act on."""


class ProviderTimeoutError(ProviderError):
    """The provider did not respond within the configured timeout."""


class ProviderRateLimitError(ProviderError):
    """The provider returned a 429 / rate-limit response."""


class ProviderAuthError(ProviderError):
    """The provider rejected the credentials (missing or invalid API key)."""


class BudgetExceededError(PebbleError):
    """A request would exceed a configured cost budget.

    Raised *before* the network call. The message identifies which budget
    was tripped (`max_tokens_per_query`, `max_embeddings_per_ingest`) and
    by how much.
    """


class StoreError(PebbleError):
    """A VectorStore operation failed (index corrupt, SQLite locked, etc.)."""
