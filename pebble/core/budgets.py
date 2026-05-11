"""Cost-budget enforcement.

A runaway loop billing the operator $200 overnight is the dominant
operational risk on a small VPS. These functions fire *before* the
network call and raise `BudgetExceededError` with a message that
identifies which budget was tripped and by how much.

Token counting uses a `chars/4` heuristic. This is intentionally
conservative — we'd rather refuse a borderline call than under-estimate
and bill the user. A more accurate `tiktoken`-based count is a one-line
swap if it ever becomes necessary.
"""

from __future__ import annotations

from pebble.core.errors import BudgetExceededError

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Approximate token count for billing-budget purposes only."""
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def enforce_query_budget(
    *,
    system: str,
    user: str,
    max_output_tokens: int,
    limit: int,
) -> None:
    """Raise `BudgetExceededError` if the call would exceed `limit` tokens.

    Bounds the sum of (estimated input tokens) + (max_output_tokens) against
    `limits.max_tokens_per_query` from config.
    """
    estimated_input = estimate_tokens(system) + estimate_tokens(user)
    total = estimated_input + max_output_tokens
    if total > limit:
        raise BudgetExceededError(
            f"query would consume ~{total} tokens "
            f"(input ~{estimated_input} + output {max_output_tokens}) "
            f"but max_tokens_per_query is {limit}"
        )


def enforce_ingest_budget(*, num_chunks: int, limit: int) -> None:
    """Raise `BudgetExceededError` if ingest would produce > `limit` embeddings."""
    if num_chunks > limit:
        raise BudgetExceededError(
            f"ingest would produce {num_chunks} embeddings "
            f"but max_embeddings_per_ingest is {limit}"
        )
