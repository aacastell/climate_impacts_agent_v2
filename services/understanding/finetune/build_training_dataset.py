"""Turns run_baseline_eval.py's real output into a real Bedrock fine-tuning dataset — the actual
"trigger" this project's fine-tuning story has been missing. No training data exists yet in the
sense of a large, dedicated human-labeled set; what exists is real, correct traces from the
baseline eval harness itself (see run_baseline_eval.py's own docstring: "the traces from
questions the baseline got right are exactly what LoRA training data ... would be built from
later" — standard teacher-distillation practice, only training on the teacher's correct outputs).
This script is that promise, kept: point it at eval_runs/*.jsonl (or a real accumulated set of
production traces later), and it produces a real, upload-ready dataset. Running it with today's
23 correct examples (see eval_runs/20260825T192046Z_traces.jsonl) produces a real, small dataset —
too small to actually submit a job against yet (see the record-count warning below), but the
pipeline itself is real and complete; growing the input is a data problem now, not a code problem.

Dataset format: Bedrock's real, documented `bedrock-conversation-2024` schema (Converse API
message format) — confirmed live against
https://docs.aws.amazon.com/bedrock/latest/userguide/model-customization-prepare.html, not
guessed. One real, flagged uncertainty, not papered over: that page's example only shows plain
`{"text": ...}` content blocks: whether Bedrock's FINE_TUNING dataset validator accepts
`toolUse`/`toolResult` content blocks (which real understanding() traces are mostly made of, since
this is a tool-calling agent) is not confirmed anywhere in that doc. Recommendation: run a small
job (a handful of records) first and read `CreateModelCustomizationJob`'s real validation
response/failure reason before committing a full run to it — see trigger_finetune_job.py.

Run with: python build_training_dataset.py [--eval-runs-dir DIR] [--out FILE] [--upload-to-s3 URI]
"""

import argparse
import json
import sys
from pathlib import Path

# Both paths, matching run_baseline_eval.py's own real, working sys.path setup exactly —
# orchestrator.py imports climate_pipeline.agent.tools, so services/understanding alone isn't
# enough (a real bug caught live: the earlier version of this file only added the first path and
# failed with ModuleNotFoundError the moment this ran for real against the real package layout,
# not a stubbed-imports check that bypassed the real import chain).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "pipeline"))
from orchestrator import SYSTEM_PROMPT  # noqa: E402

DEFAULT_EVAL_RUNS_DIR = Path(__file__).parent / "eval_runs"


def _to_bedrock_conversation_record(trace: list[dict]) -> dict:
    """trace is already a real Bedrock Converse API message list (see orchestrator.interpret()'s
    own docstring) — {"role": "user"/"assistant", "content": [...]} — which is exactly what
    `bedrock-conversation-2024`'s `messages` field expects. No reshaping needed beyond wrapping it
    with `schemaVersion` and the real system prompt this trace was actually produced under.
    """
    return {
        "schemaVersion": "bedrock-conversation-2024",
        "system": [{"text": SYSTEM_PROMPT}],
        "messages": trace,
    }


def build_dataset(eval_runs_dir: Path) -> list[dict]:
    """Reads every *_traces.jsonl in eval_runs_dir, keeps only correct==True records (teacher-
    distillation: never train on the baseline's own mistakes), and converts each to a real
    Bedrock fine-tuning record."""
    records = []
    for path in sorted(eval_runs_dir.glob("*_traces.jsonl")):
        with path.open() as f:
            for line in f:
                item = json.loads(line)
                if item["correct"] and item["result"].get("kind") != "error":
                    records.append(_to_bedrock_conversation_record(item["trace"]))
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-runs-dir", type=Path, default=DEFAULT_EVAL_RUNS_DIR)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "training_dataset.jsonl")
    parser.add_argument("--upload-to-s3", help="s3://bucket/key to also upload the dataset to, e.g. s3://<bucket>/finetune/understanding/dataset.jsonl")
    args = parser.parse_args()

    records = build_dataset(args.eval_runs_dir)

    with args.out.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    print(f"Wrote {len(records)} real, correct-only training records to {args.out}")
    if len(records) < 32:
        # 32 is Claude 3 Haiku's documented minimum, not a confirmed Nova figure — Nova's real
        # minimum is unconfirmed (see this file's own docstring); flagged as a likely-too-small
        # signal, not asserted as a hard Nova rule.
        print(
            f"WARNING: {len(records)} records is below the smallest documented Bedrock "
            "fine-tuning minimum seen for any model (32, for Claude 3 Haiku) — likely too few to "
            "submit a real job against yet. Run run_baseline_eval.py again (or accumulate real "
            "production traces) to grow this before triggering a job."
        )

    if args.upload_to_s3:
        import boto3

        bucket, _, key = args.upload_to_s3.removeprefix("s3://").partition("/")
        boto3.client("s3", region_name="us-east-1").upload_file(str(args.out), bucket, key)
        print(f"Uploaded to {args.upload_to_s3}")


if __name__ == "__main__":
    main()
