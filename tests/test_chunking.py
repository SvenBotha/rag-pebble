"""Tests for the recursive character chunker."""

from __future__ import annotations

import pytest

from pebble.core.chunking import RecursiveCharacterChunker
from pebble.core.interfaces import UNASSIGNED_CHUNK_ID, Document


def _make_doc(text: str) -> Document:
    return Document(doc_id="abc", source_path="/tmp/x.md", text=text)


def test_rejects_overlap_ge_chunk_size():
    with pytest.raises(ValueError):
        RecursiveCharacterChunker(chunk_size=100, overlap=100)


def test_rejects_non_positive_chunk_size():
    with pytest.raises(ValueError):
        RecursiveCharacterChunker(chunk_size=0, overlap=0)


def test_empty_text_yields_nothing():
    chunker = RecursiveCharacterChunker(chunk_size=100, overlap=10)
    assert list(chunker.chunk(_make_doc(""))) == []
    assert list(chunker.chunk(_make_doc("   \n  "))) == []


def test_short_text_one_chunk():
    chunker = RecursiveCharacterChunker(chunk_size=100, overlap=10)
    chunks = list(chunker.chunk(_make_doc("hello world")))
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"
    assert chunks[0].chunk_id == UNASSIGNED_CHUNK_ID
    assert chunks[0].doc_id == "abc"
    assert chunks[0].index == 0


def test_long_text_multiple_chunks_with_overlap():
    chunker = RecursiveCharacterChunker(chunk_size=80, overlap=20)
    text = "Paragraph one is here.\n\n" + ("foo bar baz " * 30)
    chunks = list(chunker.chunk(_make_doc(text)))
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 80
    # Chunks are indexed sequentially from 0.
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunker_prefers_paragraph_break():
    chunker = RecursiveCharacterChunker(chunk_size=60, overlap=10)
    # 30-char paragraph then 30-char paragraph: should split exactly between.
    text = "A" * 30 + "\n\n" + "B" * 30
    chunks = list(chunker.chunk(_make_doc(text)))
    assert len(chunks) >= 2
    # The first chunk should end before the paragraph break (no B's).
    assert "B" not in chunks[0].text


def test_chunker_propagates_doc_metadata():
    chunker = RecursiveCharacterChunker(chunk_size=50, overlap=5)
    doc = Document(
        doc_id="docid-xyz",
        source_path="/a/b/c.md",
        text="hello",
        metadata={"foo": "bar"},
    )
    chunks = list(chunker.chunk(doc))
    assert chunks[0].doc_id == "docid-xyz"
    assert chunks[0].source_path == "/a/b/c.md"
