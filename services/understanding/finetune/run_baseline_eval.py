"""Measures the real baseline (Claude Haiku via Bedrock) against eval_questions.py's hand-curated
set — real Bedrock calls, real Amazon Location geocoding, real gwl_year_table lookups, the exact
same interpret() loop understanding()'s FastAPI app runs in production. No mocks.

This is the actual evidence for "should we fine-tune, and did it help" instead of fine-tuning on
a schedule or a hunch: run this against the baseline, look at what it actually gets wrong, then
decide whether a training run is warranted and what it should specifically target.

Writes two things: a JSON summary (accuracy by category, latency) and a JSONL of full traces
(question, tool calls, tool results, final turn, correct-or-not) — the traces from questions the
baseline got right are exactly what LoRA training data (real, not fabricated, distilled from the
baseline itself) would be built from later; see interpret()'s `trace` parameter, added for this.

Run with: python run_baseline_eval.py <place-index-name> [--bucket BUCKET]
"""

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "pipeline"))

from model_client import BedrockConverseUnderstandingClient  # noqa: E402
from orchestrator import interpret  # noqa: E402

from eval_questions import EVAL_QUESTIONS, REGION_TOLERANCE_DEGREES  # noqa: E402

REGION = "us-east-2"  # the real region with actual Bedrock quota — see docs/overnight-2026-08-25.md
DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def _score(result: dict, expected: dict) -> tuple[bool, str]:
    kind = result.get("kind")
    expected_kind = expected["expected_kind"]

    if expected_kind == "clarify":
        if kind == "clarify":
            return True, "correctly asked for clarification"
        return False, f"expected clarify, got {kind!r} — {result}"

    if expected_kind == "resolved":
        if kind != "resolved":
            return False, f"expected resolved, got {kind!r} — {result}"
        if result["crop"] != expected["expected_crop"]:
            return False, f"wrong crop: got {result['crop']!r}, expected {expected['expected_crop']!r}"
        if abs(result["warmingLevelC"] - expected["expected_warming_level_c"]) > 0.01:
            return False, f"wrong warming level: got {result['warmingLevelC']}, expected {expected['expected_warming_level_c']}"
        region = result["region"]
        lon_err = abs(region["lon"] - expected["expected_region_lon"])
        lat_err = abs(region["lat"] - expected["expected_region_lat"])
        if lon_err > REGION_TOLERANCE_DEGREES or lat_err > REGION_TOLERANCE_DEGREES:
            return False, f"region too far off: got ({region['lon']}, {region['lat']}), expected near ({expected['expected_region_lon']}, {expected['expected_region_lat']})"
        return True, "correctly resolved"

    raise ValueError(f"Unknown expected_kind {expected_kind!r}")


def run_eval(model_client, location, index_name: str, gwl_year_table: list[dict], *, verbose: bool = True) -> dict:
    """Runs the full eval set once against the given model_client and returns everything a caller
    could need: per-question traces, the summary, and the raw (correct_count, n) a statistical
    drift test needs — the reusable core both main() (below) and check_drift.py call, so the
    scoring logic exists in exactly one place."""
    traces = []
    durations = []
    correct_count = 0
    by_kind: dict[str, list[bool]] = {"resolved": [], "clarify": []}

    for i, item in enumerate(EVAL_QUESTIONS, 1):
        question = item["question"]
        trace: list = []
        start = time.perf_counter()
        try:
            result = interpret(model_client, location, index_name, gwl_year_table, question, trace=trace)
        except Exception as exc:  # a real failure is data too, not something to hide by crashing the whole run
            result = {"kind": "error", "error": str(exc)}
        duration = time.perf_counter() - start
        durations.append(duration)

        is_correct, reason = _score(result, item)
        correct_count += is_correct
        by_kind[item["expected_kind"]].append(is_correct)

        if verbose:
            status = "PASS" if is_correct else "FAIL"
            print(f"[{i}/{len(EVAL_QUESTIONS)}] {status} ({duration:.2f}s) — {question!r} — {reason}")

        traces.append({
            "question": question,
            "expected": item,
            "result": result,
            "correct": is_correct,
            "reason": reason,
            "duration_s": duration,
            "trace": trace,
        })

    ms = sorted(d * 1000 for d in durations)
    p50 = ms[len(ms) // 2]
    p95 = ms[int(len(ms) * 0.95)]
    resolved_accuracy = sum(by_kind["resolved"]) / len(by_kind["resolved"]) if by_kind["resolved"] else None
    clarify_accuracy = sum(by_kind["clarify"]) / len(by_kind["clarify"]) if by_kind["clarify"] else None

    summary = {
        "run_at": datetime.now(UTC).isoformat(),
        "n_questions": len(EVAL_QUESTIONS),
        "correct_count": correct_count,
        "overall_accuracy": correct_count / len(EVAL_QUESTIONS),
        "resolved_accuracy": resolved_accuracy,
        "clarify_accuracy": clarify_accuracy,
        "latency_ms": {"p50": p50, "p95": p95, "mean": statistics.mean(ms), "max": max(ms)},
    }
    return {"summary": summary, "traces": traces, "correct_count": correct_count, "n": len(EVAL_QUESTIONS)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("index_name")
    parser.add_argument("--bucket", default="climate-impacts-isimip-raw-148323855774")
    # Overridable because the "real" baseline (Claude Haiku) is currently blocked by the
    # account's unsubmitted Anthropic use-case form — a real, separate, still-open
    # administrative gap, not something this script can work around by retrying. Passing
    # --model-id lets this run against whatever's actually reachable right now (e.g. Nova Pro)
    # without silently mislabeling the result as the Claude Haiku baseline it isn't.
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    args = parser.parse_args()

    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    location = boto3.client("location", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)

    model_client = BedrockConverseUnderstandingClient(bedrock, args.model_id)
    gwl_year_table = json.loads(
        s3.get_object(Bucket=args.bucket, Key="processed/global/gwl_year_table.json")["Body"].read()
    )

    outcome = run_eval(model_client, location, args.index_name, gwl_year_table)
    summary = {"model_id": args.model_id, **outcome["summary"]}

    print()
    print(json.dumps(summary, indent=2))

    out_dir = Path(__file__).parent / "eval_runs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"{stamp}_summary.json").write_text(json.dumps(summary, indent=2))
    with (out_dir / f"{stamp}_traces.jsonl").open("w") as f:
        for t in outcome["traces"]:
            f.write(json.dumps(t) + "\n")
    print(f"\nWrote {out_dir}/{stamp}_summary.json and {out_dir}/{stamp}_traces.jsonl")


if __name__ == "__main__":
    main()
