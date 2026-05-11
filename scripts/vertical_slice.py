"""Pebble — vertical slice (Phase 0).

The dumbest possible end-to-end RAG pipeline: ingest one markdown file,
chunk it, embed via OpenAI, store in an in-memory FAISS index, expose a
single POST /query endpoint, and a CLI that hits it.

Hardcoded values, no abstractions. This file exists as living documentation
of the simplest path through the system. It stays in the repo as a reference
once the real package lands under pebble/.

Usage:
    pip install -r scripts/requirements.txt
    export OPENAI_API_KEY=sk-...
    python scripts/vertical_slice.py serve            # builds index, runs API
    python scripts/vertical_slice.py ask "..."        # queries the running API
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import faiss
import httpx
import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Constants (hardcoded by design — config lands in Phase 2)
# ---------------------------------------------------------------------------

DOC_PATH = Path("examples/docs/sample.md")
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
TOP_K = 5
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
LLM_MODEL = "gpt-4o-mini"
TEMPERATURE = 0.2
MAX_TOKENS = 800
API_HOST = "127.0.0.1"
API_PORT = 8000

SYSTEM_PROMPT = (
    "You are a retrieval-grounded assistant. Answer the user's question using "
    "only the provided context. Each context block is prefixed with its source. "
    "Cite sources inline as [source: <path>]. If the context does not contain "
    "enough information to answer, say so explicitly and do not guess."
)

# ---------------------------------------------------------------------------
# 1. Load + chunk
# ---------------------------------------------------------------------------


def load_doc(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def chunk_text(text: str) -> list[str]:
    """Naive fixed-window chunker with overlap. Replaced by a real recursive
    chunker in Phase 2 (pebble/core/chunking.py)."""
    if CHUNK_OVERLAP >= CHUNK_SIZE:
        raise ValueError("overlap must be smaller than chunk size")
    stride = CHUNK_SIZE - CHUNK_OVERLAP
    chunks: list[str] = []
    for start in range(0, len(text), stride):
        piece = text[start : start + CHUNK_SIZE].strip()
        if piece:
            chunks.append(piece)
        if start + CHUNK_SIZE >= len(text):
            break
    return chunks


# ---------------------------------------------------------------------------
# 2. Embed
# ---------------------------------------------------------------------------


def embed(client: OpenAI, texts: list[str]) -> np.ndarray:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    vectors = np.array([d.embedding for d in resp.data], dtype="float32")
    faiss.normalize_L2(vectors)
    return vectors


# ---------------------------------------------------------------------------
# 3. In-memory FAISS index + parallel chunk store
# ---------------------------------------------------------------------------


class InMemoryIndex:
    def __init__(self) -> None:
        self.index = faiss.IndexFlatIP(EMBED_DIM)
        self.chunks: list[str] = []
        self.sources: list[str] = []

    def add(self, vectors: np.ndarray, chunks: list[str], source: str) -> None:
        assert len(vectors) == len(chunks)
        self.index.add(vectors)
        self.chunks.extend(chunks)
        self.sources.extend([source] * len(chunks))

    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, str, float]]:
        scores, ids = self.index.search(vector, top_k)
        out: list[tuple[str, str, float]] = []
        for score, idx in zip(scores[0], ids[0]):
            if idx == -1:
                continue
            out.append((self.chunks[idx], self.sources[idx], float(score)))
        return out


# ---------------------------------------------------------------------------
# 4. Prompt assembly + LLM call (template locked per brief §7)
# ---------------------------------------------------------------------------


def assemble_prompt(hits: list[tuple[str, str, float]]) -> str:
    blocks = [f"[source: {source}]\n{text}" for text, source, _ in hits]
    return "\n\n---\n\n".join(blocks)


def answer(client: OpenAI, store: InMemoryIndex, query: str) -> dict:
    query_vec = embed(client, [query])
    hits = store.search(query_vec, TOP_K)
    if not hits:
        return {"answer": "I have no context available to answer that.", "chunks": []}

    context = assemble_prompt(hits)
    user_message = f"Context:\n\n{context}\n\nQuestion: {query}"
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
    return {
        "answer": resp.choices[0].message.content or "",
        "chunks": [
            {"text": text, "source_path": source, "score": score}
            for text, source, score in hits
        ],
    }


# ---------------------------------------------------------------------------
# 5. FastAPI surface
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    query: str
    debug: bool = False


class ChunkOut(BaseModel):
    text: str
    source_path: str
    score: float


class QueryResponse(BaseModel):
    answer: str
    chunks: list[ChunkOut] = []


def build_app() -> FastAPI:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = OpenAI()
    store = InMemoryIndex()

    text = load_doc(DOC_PATH)
    chunks = chunk_text(text)
    vectors = embed(client, chunks)
    store.add(vectors, chunks, source=str(DOC_PATH))
    print(f"[vertical-slice] indexed {len(chunks)} chunks from {DOC_PATH}")

    app = FastAPI(title="pebble-vertical-slice")

    @app.post("/query", response_model=QueryResponse)
    def query_endpoint(req: QueryRequest) -> QueryResponse:
        result = answer(client, store, req.query)
        return QueryResponse(
            answer=result["answer"],
            chunks=[ChunkOut(**c) for c in result["chunks"]] if req.debug else [],
        )

    return app


# ---------------------------------------------------------------------------
# 6. CLI entry
# ---------------------------------------------------------------------------


def cli_ask(question: str, debug: bool = False) -> None:
    url = f"http://{API_HOST}:{API_PORT}/query"
    try:
        resp = httpx.post(url, json={"query": question, "debug": debug}, timeout=60.0)
    except httpx.ConnectError:
        print(f"error: cannot reach {url} — is `serve` running?", file=sys.stderr)
        sys.exit(1)
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.text)
    data = resp.json()
    print(data["answer"])
    if debug:
        print("\n--- retrieved chunks ---")
        for c in data["chunks"]:
            print(f"\n[{c['score']:.3f}] {c['source_path']}\n{c['text']}")


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] not in {"serve", "ask"}:
        print("usage: vertical_slice.py {serve | ask <question> [--debug]}", file=sys.stderr)
        sys.exit(2)

    if argv[1] == "serve":
        uvicorn.run(build_app(), host=API_HOST, port=API_PORT)
        return

    if len(argv) < 3:
        print("usage: vertical_slice.py ask <question> [--debug]", file=sys.stderr)
        sys.exit(2)
    debug = "--debug" in argv[3:]
    question = argv[2]
    cli_ask(question, debug=debug)


if __name__ == "__main__":
    main(sys.argv)
