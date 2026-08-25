"""Real latency/throughput benchmark for Phase 1's query-time lookup (climate_pipeline.query.
lookup.lookup_value) — the one component in the whole system that's fully real, deployed data,
and not blocked by tonight's Bedrock quota issue. Measures against real S3 objects, not fakes.

Two cost regimes matter and this measures both separately:
- Cold: first request for a given (field, year) — a real S3 GetObject for a ~1MB NetCDF file plus
  opening it. This is what a fresh Lambda cold start, or the first query for a not-yet-cached
  field-window, actually pays.
- Warm: the file already exists locally (Lambda execution environment reuse, or /tmp persisting
  across invocations on the same warm container) — no network call, just re-opening a local file
  already on disk and doing the nearest-cell selection.

Run with: python -m benchmarks.query_latency_benchmark --bucket <bucket>
"""

import argparse
import shutil
import statistics
import time
from pathlib import Path

import boto3

from climate_pipeline.query.lookup import download_field_window, nearest_cell_value

# Real region points, matching the values already in climate_pipeline/agent/tools.py.
SAMPLE_POINTS = [
    ("Iowa", -93.6, 42.0),
    ("Punjab", 75.3, 31.1),
    ("Occitanie", 2.15, 43.6),
]


def _bench_cold(s3, bucket: str, field: str, kind: str, year: int, work_dir: Path, n: int) -> list[float]:
    """Each iteration gets its own fresh work_dir — forces a real S3 download every time, no
    local-file reuse across iterations."""
    durations = []
    for i in range(n):
        iter_dir = work_dir / f"cold_{i}"
        start = time.perf_counter()
        path = download_field_window(s3, bucket, field, kind, year, iter_dir)
        nearest_cell_value(path, field, kind, SAMPLE_POINTS[0][1], SAMPLE_POINTS[0][2])
        durations.append(time.perf_counter() - start)
    return durations


def _bench_warm(s3, bucket: str, field: str, kind: str, year: int, work_dir: Path, n: int) -> list[float]:
    """One real download, then repeated local reads+lookups — no network involved after the
    first call, matching a warm Lambda execution environment."""
    warm_dir = work_dir / "warm"
    path = download_field_window(s3, bucket, field, kind, year, warm_dir)
    durations = []
    for name, lon, lat in SAMPLE_POINTS * (n // len(SAMPLE_POINTS) + 1):
        if len(durations) >= n:
            break
        start = time.perf_counter()
        nearest_cell_value(path, field, kind, lon, lat)
        durations.append(time.perf_counter() - start)
    return durations


def _summarize(label: str, durations: list[float]) -> None:
    ms = sorted(d * 1000 for d in durations)
    p50 = ms[len(ms) // 2]
    p95 = ms[int(len(ms) * 0.95)] if len(ms) > 1 else ms[0]
    print(
        f"{label}: n={len(ms)} mean={statistics.mean(ms):.1f}ms p50={p50:.1f}ms "
        f"p95={p95:.1f}ms min={min(ms):.1f}ms max={max(ms):.1f}ms"
    )
    if p50 > 0:
        # Single-threaded-equivalent throughput — real concurrency (async/threadpool) multiplies
        # this, not a hard ceiling on its own.
        print(f"  -> ~{1000 / p50:.1f} requests/sec sustained on a single sequential worker")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--field", default="maize")
    parser.add_argument("--kind", default="percent")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()

    s3 = boto3.client("s3")
    work_dir = Path("/tmp/query_latency_benchmark")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    print(f"Benchmarking lookup_value's two real cost components: {args.field}/{args.kind} y{args.year}\n")

    cold = _bench_cold(s3, args.bucket, args.field, args.kind, args.year, work_dir, args.iterations)
    _summarize("COLD (real S3 download + open + lookup)", cold)

    warm = _bench_warm(s3, args.bucket, args.field, args.kind, args.year, work_dir, args.iterations * 3)
    _summarize("WARM (local file already present, open + lookup only)", warm)

    shutil.rmtree(work_dir)


if __name__ == "__main__":
    main()
