#!/usr/bin/env bash
# Triggers the process_global DVC stage — the real global precompute grid (see
# pipeline/climate_pipeline/process/run.py, pipeline/README.md). Deliberately its own script, not
# folded into run-isimip-fetch.sh: fetch and process are separate DVC stages for real reasons
# (ADR-006 Step 8 — different lifecycles, different reasons to re-run), and merging their trigger
# scripts would undo that separation at the orchestration layer even though dvc.yaml itself keeps
# them apart.
#
# Runs on the same CodeBuild project as fetch (ClimateImpactsIsimipFetch) — see pipeline/README.md
# on why: nothing about this workload has demonstrated a need for separate infrastructure yet,
# revisit once real profiling data says otherwise, the same way fetch's own sizing was only set
# once its real volume was known.
#
# This is a single stage, not a set of groups like fetch's 5-way split — no chunking here unless/
# until a real run shows it doesn't fit inside the account's ~45-minute CodeBuild cap.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_NAME="ClimateImpactsIsimipFetch"
# 50 min: comfortably past the ~45-min cap, so this script observes whichever terminal status
# CodeBuild actually reaches (SUCCEEDED or the account-level TIMED_OUT) instead of giving up
# first. Whether process_global actually fits inside that cap is genuinely unverified — this is
# real profiling, not an assumption already tested.
MAX_WAIT_MINUTES=50

"$ROOT/scripts/run-codebuild.sh" "$PROJECT_NAME" "$MAX_WAIT_MINUTES" process_global
