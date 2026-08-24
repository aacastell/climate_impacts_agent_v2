"""Records how long a fetch stage actually took, at what throughput, and
saves it as a durable, timestamped record in S3.

CodeBuild's own build report (`aws codebuild batch-get-builds`) already
gives phase-level timing for free — install/build/etc. durations, no work
needed there. What it can't see is the gap this fills: all 12 fetch stages
run inside one opaque `BUILD` phase (a single `dvc repro` invocation), so
CodeBuild has no idea how long fetching `tas` baseline took versus `rice`
future, or what the real transfer throughput was. That's only visible from
inside this code, which is why it's recorded here rather than relied on
from AWS's side.

Not DVC-tracked: this is observability data, not a scientific data product
needing lineage/reproducibility, so it doesn't belong in dvc.yaml's stage
graph. A direct S3 write, same bucket, separate namespace from raw/.
"""

import json
from datetime import UTC, datetime

import boto3


def record_run(bucket: str, stage: str, started_at: datetime, file_manifests: list[dict]) -> str:
    """Summarize one fetch stage's run (started_at to now) across all the
    files it touched, and write that summary to S3.

    Args: bucket — where to write the record. stage — a name identifying
        this fetch stage (e.g. "tas_baseline", "lpjml_maize_future").
        started_at — when this stage's fetch began. file_manifests — the
        per-file manifests stream_file_to_s3 returned for every file this
        stage touched.
    Returns: the S3 key the record was written to.
    """
    finished_at = datetime.now(UTC)
    duration_seconds = (finished_at - started_at).total_seconds()
    fetched = [f for f in file_manifests if not f.get("skipped_fetch")]
    skipped = [f for f in file_manifests if f.get("skipped_fetch")]
    total_bytes = sum(f["size_bytes"] for f in file_manifests)
    fetched_bytes = sum(f["size_bytes"] for f in fetched)

    record = {
        "stage": stage,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round(duration_seconds, 2),
        "file_count": len(file_manifests),
        "fetched_count": len(fetched),
        "skipped_count": len(skipped),
        "total_bytes": total_bytes,
        "fetched_bytes": fetched_bytes,
        # Only meaningful across the files actually transferred this run —
        # a stage that skipped everything has no throughput to report.
        "throughput_mbps": round((fetched_bytes * 8 / 1_000_000) / duration_seconds, 2)
        if fetched and duration_seconds > 0
        else None,
    }

    key = f"_profiling/{started_at.strftime('%Y-%m-%dT%H-%M-%S')}Z/{stage}.json"
    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(record, indent=2, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )
    return key
