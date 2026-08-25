"""Real latency benchmark for geocode() against Amazon Location Service — the one piece of
understanding()'s tool set that's real, deployed, and not blocked by the Bedrock quota issue.
Run with: python benchmark_geocode.py <index-name>
"""

import statistics
import sys
import time

import boto3

sys.path.insert(0, "../../pipeline")
from climate_pipeline.agent.tools import geocode

QUERIES = ["Iowa", "Mekong Delta", "Punjab", "Occitanie", "Nile Delta"]


def main() -> None:
    index_name = sys.argv[1] if len(sys.argv) > 1 else "geocode-verification-test"
    location = boto3.client("location", region_name="us-east-1")

    durations = []
    for query in QUERIES * 4:
        start = time.perf_counter()
        geocode(location, index_name, query)
        durations.append(time.perf_counter() - start)

    ms = sorted(d * 1000 for d in durations)
    p50 = ms[len(ms) // 2]
    p95 = ms[int(len(ms) * 0.95)]
    print(f"geocode(): n={len(ms)} mean={statistics.mean(ms):.1f}ms p50={p50:.1f}ms p95={p95:.1f}ms min={min(ms):.1f}ms max={max(ms):.1f}ms")
    print(f"  -> ~{1000 / p50:.1f} requests/sec sustained on a single sequential worker")


if __name__ == "__main__":
    main()
