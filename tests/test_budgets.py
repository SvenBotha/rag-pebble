"""Tests for cost-budget enforcement."""

from __future__ import annotations

import pytest

from pebble.core.budgets import (
    enforce_ingest_budget,
    enforce_query_budget,
    estimate_tokens,
)
from pebble.core.errors import BudgetExceededError


def test_estimate_tokens_empty_is_zero():
    assert estimate_tokens("") == 0


def test_estimate_tokens_rough_chars_over_4():
    # Heuristic: max(1, len // 4). "abcdefgh" (8 chars) → 2.
    assert estimate_tokens("abcdefgh") == 2
    assert estimate_tokens("a") == 1


def test_enforce_query_budget_passes_under_limit():
    enforce_query_budget(
        system="short system prompt",
        user="short user message",
        max_output_tokens=100,
        limit=10000,
    )


def test_enforce_query_budget_raises_over_limit():
    big_user = "x" * 4000  # ~1000 input tokens
    with pytest.raises(BudgetExceededError) as excinfo:
        enforce_query_budget(
            system="sys",
            user=big_user,
            max_output_tokens=500,
            limit=100,
        )
    assert "max_tokens_per_query" in str(excinfo.value)


def test_enforce_ingest_budget_passes_under_limit():
    enforce_ingest_budget(num_chunks=100, limit=1000)


def test_enforce_ingest_budget_raises_over_limit():
    with pytest.raises(BudgetExceededError) as excinfo:
        enforce_ingest_budget(num_chunks=1001, limit=1000)
    assert "max_embeddings_per_ingest" in str(excinfo.value)
