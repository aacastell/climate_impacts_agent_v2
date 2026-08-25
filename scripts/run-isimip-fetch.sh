#!/usr/bin/env bash
# Runs each of the 13 ISIMIP/GGCMI fetch stages — each its own fully
# independent CodeBuild project (see infra/stacks/pipeline_step_build_project_stack.py
# and infra/app.py's FETCH_STEPS), command baked in at the project level, no
# override needed. Nothing here can pull another stage along as a side
# effect — that's the whole point of per-step project separation.
#
# This account's CodeBuild builds are capped at ~45 minutes regardless of
# the project's own configured timeout (confirmed against real build
# records) — each of these stages individually fits comfortably inside
# that.
#
# Sequential, not parallel: each build is independent enough to run in
# parallel safely, but this account's concurrent-build limit hasn't been
# profiled against running all 13 (plus 8 process builds) at once —
# sequential is the safe default until that's actually measured, not a
# coupling decision.
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

for project in "${FETCH_PROJECTS[@]}"; do
  echo "==> Fetch: $project"
  "$ROOT/scripts/run-codebuild.sh" "$project" "$MAX_WAIT_MINUTES"
done

echo "==> All 13 ISIMIP fetch stages completed"
