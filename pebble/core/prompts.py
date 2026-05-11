"""Prompt assembly.

One template. One place. Every retrieval-grounded call from Pebble
goes through these two definitions. Changing the template is a one-line
diff that shows up cleanly in code review.
"""

from __future__ import annotations

from collections.abc import Sequence

from pebble.core.interfaces import RetrievedChunk

SYSTEM_PROMPT = (
    "You are a retrieval-grounded assistant. Answer the user's question "
    "using only the provided context. Each context block is prefixed with "
    "its source. Cite sources inline as [source: <path>]. If the context "
    "does not contain enough information to answer, say so explicitly and "
    "do not guess."
)

BLOCK_SEPARATOR = "\n\n---\n\n"


def assemble_user_message(query: str, hits: Sequence[RetrievedChunk]) -> str:
    """Build the user-side prompt from a query and ranked chunks.

    Chunks are emitted in the order provided — the caller is responsible
    for sorting by descending score before passing them in.
    """
    if not hits:
        return f"Context:\n\n(no context retrieved)\n\nQuestion: {query}"

    blocks = [f"[source: {h.chunk.source_path}]\n{h.chunk.text}" for h in hits]
    return f"Context:\n\n{BLOCK_SEPARATOR.join(blocks)}\n\nQuestion: {query}"
