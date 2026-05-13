"""Download a Wikipedia subset and write it to disk as markdown files.

Streams from HuggingFace's `wikimedia/wikipedia` dataset so we never
materialise the whole dump in memory. Each article becomes one .md file
with the title as an H1 and the body following.

Usage:
    uv run python bench/prepare_corpus.py                 # 1000 simple-wiki articles
    uv run python bench/prepare_corpus.py --count 25000   # ~50k chunks (memory test)
    uv run python bench/prepare_corpus.py --variant 20231101.en --count 5000

Scale guidance for the §8 memory check (50k chunks @ chunk_size=800):
- Simple English Wikipedia: avg ~1500 chars/article → ~25k articles
- English Wikipedia:        avg ~4000 chars/article → ~10k articles
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from datasets import load_dataset

DEFAULT_VARIANT = "20231101.simple"
DEFAULT_OUT = Path("data/corpus")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument(
        "--variant",
        default=DEFAULT_VARIANT,
        help="HuggingFace wikimedia/wikipedia config (e.g. 20231101.simple, 20231101.en)",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    print(f"streaming wikimedia/wikipedia {args.variant!r}, writing to {args.out}/")

    ds = load_dataset(
        "wikimedia/wikipedia",
        args.variant,
        split="train",
        streaming=True,
    )

    total_chars = 0
    written = 0
    for row in ds:
        if written >= args.count:
            break
        title = row.get("title", "Untitled")
        text = row.get("text", "") or ""
        if not text.strip():
            continue
        path = args.out / f"{written:05d}.md"
        path.write_text(f"# {title}\n\n{text}", encoding="utf-8")
        total_chars += len(text)
        written += 1
        if written % 100 == 0:
            print(f"  {written}/{args.count} articles, {total_chars / 1_000_000:.1f}M chars so far")

    avg = total_chars / written if written else 0
    est_chunks = total_chars // 700  # chunk_size=800, overlap=100 → stride 700
    print(
        f"\ndone: {written} articles, {total_chars / 1_000_000:.1f}M chars total"
        f"\n  avg article: {avg:,.0f} chars"
        f"\n  estimated chunks @ chunk_size=800/overlap=100: ~{est_chunks:,}"
    )


if __name__ == "__main__":
    main()
    # Work is done and files are flushed. Skip Python finalisation to avoid
    # a pyarrow/datasets shutdown crash (PyGILState_Release in a non-GIL
    # thread) that surfaces with current pyarrow + Python 3.12 combinations.
    os._exit(0)
