# Retrieval improvements

To-do items focused only on **improving what gets retrieved** into the prompt (not prompting, UX copy, or non-RAG fallbacks).

- [ ] **Prompt Upgrading** - Update the prompt to allow for better reasoning for broader questions.

- [ ] **Corpus alignment** — Ingest documents that cover the domains and intents you actually want to answer (breadth beats clever retrieval alone).
- [ ] **Document preprocessing** — Strip repeated headers, footers, nav menus, and PDF extraction artifacts before chunking. Each chunk goes into the index verbatim; junk in the source means junk retrieved.
- [ ] **Chunking** — Tune `chunk_size`, `overlap`, and chunking strategy so each chunk carries a coherent unit that matches typical questions (`config.yaml` → `chunking`). The current recursive character splitter is a solid baseline; consider a sentence-aware or markdown-header-aware strategy once you have retrieval quality data.
- [ ] **Contextual chunk enrichment** — Prepend the document title or source path to each chunk's text *before* embedding (e.g. `"Source: refunds.md\n{chunk_text}"`). Cheap one-line change in the chunker; significantly helps when the chunk text is ambiguous without context.
- [ ] **`top_k` and thresholds** — Adjust `retrieval.top_k` and `similarity_threshold` so enough relevant snippets pass without drowning the prompt in noise. The current default `similarity_threshold: 0.0` means no filtering at all — setting a floor (e.g. 0.3–0.5) is usually a quick win.
- [ ] **Embeddings model** — Revisit embedding model/provider once you have a retrieval quality baseline. Different models embed technical vs. conversational language differently. Changing model requires full re-ingestion and index rebuild.
- [ ] **Matryoshka dimension reduction** — `text-embedding-3-small` supports Matryoshka embeddings: you can truncate from 1536 → 256 or 512 dims with ~5% quality loss but a ~3–6× smaller FAISS index and faster search. Requires changing `EMBED_DIM` in config and full re-ingestion.
- [ ] **Reranking** — Add a rerank step (e.g. Cohere Rerank API or a small cross-encoder) on the initial vector shortlist before building context. High-value improvement to retrieval precision, but adds one extra API call per query — measure the latency impact before enabling on a small VPS.
- [ ] **`hybrid` retrieval** — Implement the schema's `hybrid` mode (dense vectors + lexical/BM25 search). Already stubbed in `pebble/core/retrieval.py` as `HybridRetriever`. Helps most for keyword-heavy queries where vector similarity undershoots.
- [ ] **Diversity / dedup** — Reduce near-duplicate chunks in the retrieved set (e.g. MMR or a max-passages-per-document cap) so `top_k` slots carry genuinely distinct information.
- [ ] **Metadata filters** — If chunks are tagged at ingest (source, date, topic), add optional filter predicates to retrieval so answers stay in scope. Requires consistent metadata at ingest time.
- [ ] **Query expansion / rewriting** — Preprocess user queries (synonym expansion, multi-query) before embedding search. **Use with caution**: a rewriter that introduces terms not present in your corpus can actively hurt retrieval. Measure precision/recall against a baseline before deploying; the latency and cost of an extra LLM call must pay for itself in retrieval quality.
