#!/usr/bin/env bash
# Runs all 13 ISIMIP/GGCMI fetch stages in parallel — each its own fully
# independent CodeBuild project (see infra/stacks/pipeline_step_build_project_stack.py
# and infra/app.py's FETCH_STEPS), command baked in at the project level, no
# override needed. Nothing here can pull another stage along as a side
# effect — that's the whole point of per-step project separation, and it's
# exactly what makes real parallel execution safe: these are independent
# processes on independent compute, not competing for shared state.
#
# 13 concurrent builds, comfortably under this account's real, checked
# concurrent-build limit for the Linux/Medium environment (15 — confirmed
# via `aws service-quotas`, not assumed).
#
# This account's CodeBuild builds are capped at ~45 minutes regardless of
# the project's own configured timeout (confirmed against real build
# records) — each of these stages individually fits comfortably inside
# that.
#
# Safe to re-run: the per-file S3 checksum skip-check in stream_to_s3.py
# means already-fetched files are skipped almost instantly, not
# re-downloaded.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAX_WAIT_MINUTES=50

FETCH_PROJECTS=(
  "ClimateImpactsFetchTasBaseline"
  "ClimateImpactsFetchTasFuture"
  "ClimateImpactsFetchTasPreindustrial"
  "ClimateImpactsFetchPrBaseline"
  "ClimateImpactsFetchPrFuture"
  "ClimateImpactsFetchMaizeBaseline"
  "ClimateImpactsFetchMaizeFuture"
  "ClimateImpactsFetchSpringWheatBaseline"
  "ClimateImpactsFetchSpringWheatFuture"
  "ClimateImpactsFetchSoyBaseline"
  "ClimateImpactsFetchSoyFuture"
  "ClimateImpactsFetchRiceBaseline"
  "ClimateImpactsFetchRiceFuture"
)

MAX_WAIT_MINUTES="$MAX_WAIT_MINUTES" "$ROOT/scripts/run-codebuild-parallel.sh" "${FETCH_PROJECTS[@]}"

echo "==> All 13 ISIMIP fetch stages completed"
