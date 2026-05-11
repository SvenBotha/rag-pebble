"""Document chunking.

The recursive character chunker walks the text once and breaks on the
strongest available separator near each chunk boundary, falling back to
a hard cut if no separator is within range. Each chunk yields with
`chunk_id = UNASSIGNED_CHUNK_ID`; the pipeline reserves real IDs via
`VectorStore.allocate_chunk_ids` before insertion.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime

from pebble.core.interfaces import UNASSIGNED_CHUNK_ID, Chunk, Document

# Preferred break points, strongest first.
_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ")


class RecursiveCharacterChunker:
    """Fixed-window chunker that prefers natural break points.

    Each chunk is `<= chunk_size` characters. Consecutive chunks overlap
    by approximately `overlap` characters.
    """

    def __init__(self, chunk_size: int, overlap: int) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, doc: Document) -> Iterable[Chunk]:
        text = doc.text
        if not text.strip():
            return

        now = datetime.now(UTC)
        for index, piece in enumerate(self._split(text)):
            yield Chunk(
                chunk_id=UNASSIGNED_CHUNK_ID,
                doc_id=doc.doc_id,
                text=piece,
                index=index,
                source_path=doc.source_path,
                created_at=now,
                metadata={},
            )

    def _split(self, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        n = len(text)
        while start < n:
            end = start + self.chunk_size
            if end >= n:
                tail = text[start:].strip()
                if tail:
                    chunks.append(tail)
                break

            # Try to break on the strongest separator that lands in the
            # second half of the window (avoids producing tiny chunks).
            break_at = -1
            min_break = start + self.chunk_size // 2
            for sep in _SEPARATORS:
                idx = text.rfind(sep, min_break, end)
                if idx != -1:
                    break_at = idx + len(sep)
                    break
            if break_at == -1:
                break_at = end

            piece = text[start:break_at].strip()
            if piece:
                chunks.append(piece)

            next_start = break_at - self.overlap
            # Always move forward, even if overlap would push us back.
            start = max(start + 1, next_start)

        return chunks


__all__ = ["RecursiveCharacterChunker", "replace"]
