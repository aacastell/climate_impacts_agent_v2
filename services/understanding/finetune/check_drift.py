"""The scheduled drift check itself: run the real eval harness against whatever's in production
right now, compare it to a stored baseline via a real statistical test (drift_stats.py), and log
the result to MLflow as a genuine time series — not a one-off print.

Baseline is fixed, not rolling, by deliberate choice: a rolling baseline (replaced by whatever ran
last) risks the classic drift-monitoring failure mode where the reference silently drifts along
with the thing being measured and a real, gradual regression never trips any check. Updating the
baseline is a separate, explicit action (--set-baseline), not something this script does on its
own as a side effect of running.

Meant to run infrequently (e.g. weekly via a scheduled CodeBuild project — not yet wired, see
docs), not after every call — repeated significance testing inflates the true false-positive rate
well past the nominal alpha (drift_stats.py's docstring). This script computes one check; running
it in a tight loop would be a real misuse of it, not a stress test of it.

Run with: python check_drift.py <place-index-name> [--bucket BUCKET] [--model-id MODEL_ID] [--set-baseline]
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import boto3
import mlflow

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "pipeline"))

from model_client import BedrockConverseUnderstandingClient  # noqa: E402

from drift_stats import detect_drift  # noqa: E402
from run_baseline_eval import DEFAULT_MODEL_ID, REGION, run_eval  # noqa: E402

BASELINE_KEY = "eval/understanding_baseline.json"


def _load_baseline(s3, bucket: str) -> dict | None:
    try:
        obj = s3.get_object(Bucket=bucket, Key=BASELINE_KEY)
    except s3.exceptions.NoSuchKey:
        return None
    return json.loads(obj["Body"].read())


def _write_baseline(s3, bucket: str, baseline: dict) -> None:
    s3.put_object(Bucket=bucket, Key=BASELINE_KEY, Body=json.dumps(baseline, indent=2).encode("utf-8"), ContentType="application/json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("index_name")
    parser.add_argument("--bucket", default="climate-impacts-isimip-raw-148323855774")
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--set-baseline", action="store_true", help="Record this run as the new baseline instead of comparing against the existing one.")
    args = parser.parse_args()

    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    location = boto3.client("location", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)

    model_client = BedrockConverseUnderstandingClient(bedrock, args.model_id)
    gwl_year_table = json.loads(
        s3.get_object(Bucket=args.bucket, Key="processed/global/gwl_year_table.json")["Body"].read()
    )

    print(f"Running eval against model_id={args.model_id} ...")
    outcome = run_eval(model_client, location, args.index_name, gwl_year_table, verbose=False)
    current = {
        "model_id": args.model_id,
        "correct_count": outcome["correct_count"],
        "n": outcome["n"],
        "accuracy": outcome["summary"]["overall_accuracy"],
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    print(f"Current run: {current['correct_count']}/{current['n']} = {current['accuracy']:.1%}")

    existing_baseline = _load_baseline(s3, args.bucket)

    if args.set_baseline or existing_baseline is None:
        _write_baseline(s3, args.bucket, current)
        reason = "explicit --set-baseline" if args.set_baseline else "no baseline existed yet (bootstrap)"
        print(f"Wrote this run as the new baseline ({reason}). Nothing to compare against this time.")
        with mlflow.start_run(run_name=f"understanding-drift-check-baseline-{current['recorded_at']}"):
            mlflow.log_params({"model_id": args.model_id, "role": "baseline"})
            mlflow.log_metric("accuracy", current["accuracy"])
        return

    result = detect_drift(
        baseline_correct=existing_baseline["correct_count"],
        baseline_n=existing_baseline["n"],
        current_correct=current["correct_count"],
        current_n=current["n"],
    )

    print()
    print(f"Baseline ({existing_baseline['model_id']}, recorded {existing_baseline['recorded_at']}): {result['baseline_accuracy']:.1%}")
    print(f"Current  ({args.model_id}, recorded {current['recorded_at']}): {result['current_accuracy']:.1%}")
    print(f"delta={result['delta']:+.1%}  z={result['z_statistic']:.3f}  p={result['p_value']:.4f}  alpha={result['alpha']}")
    print("DRIFT DETECTED" if result["drift_detected"] else "No significant drift detected")

    with mlflow.start_run(run_name=f"understanding-drift-check-{current['recorded_at']}"):
        mlflow.log_params({
            "model_id": args.model_id,
            "baseline_model_id": existing_baseline["model_id"],
            "baseline_recorded_at": existing_baseline["recorded_at"],
            "role": "check",
        })
        mlflow.log_metrics({
            "accuracy": result["current_accuracy"],
            "baseline_accuracy": result["baseline_accuracy"],
            "delta": result["delta"],
            "z_statistic": result["z_statistic"],
            "p_value": result["p_value"],
            "drift_detected": 1.0 if result["drift_detected"] else 0.0,
        })

    if result["drift_detected"]:
        sys.exit(1)  # real signal for a scheduled job to alert on, not just a print a human might miss


if __name__ == "__main__":
    main()
