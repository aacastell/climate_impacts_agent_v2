"""Writes the small JSON manifest DVC tracks in place of the raw payload — see ADR-006 Step 8."""

import json
from pathlib import Path


def write_manifest(manifest: dict | list, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return out_path


def upload_manifest(s3, bucket: str, manifest: dict | list, key: str) -> None:
    """Uploads the manifest to a plain, fixed S3 key — not DVC's own cache-addressed storage
    (what `dvc push` writes to, keyed by content hash). This is what lets each process stage
    invocation fetch a fetch stage's output directly by a known key, with no DVC graph traversal
    involved at all — every fetch and process invocation is now a fully independent CLI call, not
    routed through `dvc repro` (see pipeline/README.md on why: dvc.lock was never committed to
    git, so a fresh CodeBuild checkout has no record of what's already done, and `dvc repro`
    re-executes the whole upstream graph every time regardless of which single stage was asked
    for)."""
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(manifest, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )
