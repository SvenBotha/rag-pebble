"""Phase 3 load test: ingest a corpus, run queries, measure RSS.

Verifies the §8 acceptance criteria that can be observed at runtime:
- Resident memory under 400 MB with the loaded index
- /ready behaviour is implicitly tested by the ingestion pause
- Query latency p50/p95 are reported

Usage:
    export OPENAI_API_KEY=sk-...
    uv run python bench/prepare_corpus.py --count 25000
    uv run python bench/run_load_test.py --corpus ./data/corpus --queries 100

Cost guidance for the defaults (50k chunks + 100 queries with
text-embedding-3-small + gpt-4o-mini): roughly $0.20–$0.25 per run.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import resource
import statistics
import time
from pathlib import Path

from pebble.bootstrap import build_services
from pebble.config.loader import load_config

# Generic factual questions that should find at least some context in
# almost any Wikipedia subset, plus a few designed to miss.
SAMPLE_QUERIES: list[str] = [
    "What is a computer?",
    "Where is Paris located?",
    "What is the human body made of?",
    "How does an engine work?",
    "What is mathematics?",
    "What is electricity?",
    "Who was Albert Einstein?",
    "What is a planet?",
    "What language is spoken in Japan?",
    "What is the largest ocean?",
    "What is a cell in biology?",
    "How tall is Mount Everest?",
    "What is the speed of light?",
    "What is a democracy?",
    "What is photosynthesis?",
    "What is gravity?",
    "Who invented the telephone?",
    "What is the population of China?",
    "What is the chemical symbol for water?",
    "What is the speed of sound?",
]


def rss_mb() -> float:
    """Resident set size in MB. Reads ru_maxrss (peak, kB on Linux)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _fmt(label: str, value: float | int, unit: str = "") -> str:
    return f"  {label:<28} {value!s:>12}{unit}"


def _make_ingest_progress(every: int = 100):  # type: ignore[no-untyped-def]
    """Print a status line every `every` documents."""
    start = time.monotonic()

    def cb(_path: Path, docs: int, chunks: int) -> None:
        if docs == 1 or docs % every == 0:
            elapsed = time.monotonic() - start
            rate = docs / elapsed if elapsed > 0 else 0.0
            print(
                f"  [RSS {rss_mb():.0f} MB] {docs} docs, {chunks} chunks "
                f"({rate:.1f} docs/s, {elapsed:.0f}s elapsed)"
            )

    return cb


async def run(corpus: Path, num_queries: int, config_path: Path | None) -> int:
    print(f"[RSS {rss_mb():.1f} MB] starting load test")

    config = load_config(config_path)
    services = build_services(config)
    live = services.store.live_count
    print(f"[RSS {rss_mb():.1f} MB] services built (initial live_count={live})")

    exit_code = 0
    try:
        # ---- Ingest --------------------------------------------------------
        print(f"\n[RSS {rss_mb():.1f} MB] ingesting corpus from {corpus}/")
        t0 = time.monotonic()
        result = await services.ingest.ingest_paths(
            [corpus],
            on_progress=_make_ingest_progress(every=100),
        )
        ingest_elapsed = time.monotonic() - t0
        print(
            f"\n[RSS {rss_mb():.1f} MB] ingest complete in {ingest_elapsed:.1f}s"
        )
        print(_fmt("ingested_documents", result.ingested_documents))
        print(_fmt("ingested_chunks", result.ingested_chunks))
        print(_fmt("skipped", result.skipped))
        print(_fmt("docs/sec", round(result.ingested_documents / max(ingest_elapsed, 1e-6), 2)))
        print(_fmt("chunks/sec", round(result.ingested_chunks / max(ingest_elapsed, 1e-6), 1)))

        # ---- Queries -------------------------------------------------------
        latencies: list[float] = []
        cycle_len = (num_queries + len(SAMPLE_QUERIES) - 1) // len(SAMPLE_QUERIES)
        queries = (SAMPLE_QUERIES * cycle_len)[:num_queries]

        t0 = time.monotonic()
        for q in queries:
            t = time.monotonic()
            await services.query.ask(q)
            latencies.append(time.monotonic() - t)
        total_query_elapsed = time.monotonic() - t0

        p50 = statistics.median(latencies) * 1000
        if len(latencies) >= 20:
            p95 = statistics.quantiles(latencies, n=20)[18] * 1000
        else:
            p95 = max(latencies) * 1000
        mean = statistics.fmean(latencies) * 1000

        print(f"\n[RSS {rss_mb():.1f} MB] {num_queries} queries in {total_query_elapsed:.1f}s")
        print(_fmt("mean latency", round(mean), " ms"))
        print(_fmt("p50 latency", round(p50), " ms"))
        print(_fmt("p95 latency", round(p95), " ms"))

        # ---- Acceptance ----------------------------------------------------
        final_rss = rss_mb()
        target = 400.0
        verdict = "PASS" if final_rss <= target else "FAIL"
        print(f"\n[acceptance §8] RSS {final_rss:.1f} MB vs target {target:.0f} MB → {verdict}")
        if final_rss > target:
            exit_code = 1

    finally:
        await services.aclose()

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/corpus"))
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()

    if not args.corpus.is_dir():
        raise SystemExit(f"corpus directory not found: {args.corpus}")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")

    raise SystemExit(asyncio.run(run(args.corpus, args.queries, args.config)))


if __name__ == "__main__":
    main()
