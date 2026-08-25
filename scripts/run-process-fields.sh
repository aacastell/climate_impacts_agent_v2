#!/usr/bin/env bash
# Runs each of the 8 process fields — each its own fully independent
# CodeBuild project (see infra/stacks/pipeline_step_build_project_stack.py
# and infra/app.py's PROCESS_STEPS), command baked in at the project level.
#
# Replaces the earlier single process_global CodeBuild run: real profiling
# showed that monolithic run TIMED_OUT after ~41 minutes of silent
# execution without completing all 67 years x 8 fields, and it was routed
# through `dvc repro process_global`, which re-executed the entire upstream
# fetch graph every time (dvc.lock isn't committed to git) — see
# climate_pipeline/process/run.py's module docstring. Per-field granularity
# fixes both: each field computes its own baseline + all 67 future years
# independently, needing only its own two fetch manifests (downloaded
# directly from a fixed S3 key, no DVC involved), and is sized to fit
# comfortably inside the account's ~45-minute CodeBuild cap on its own.
#
# Sequential, not parallel — see run-isimip-fetch.sh's same note; this
# account's concurrent-build limit hasn't been profiled against running
# fetch and process builds simultaneously.
#
# Safe to re-run: each field has its own whole-run input-fingerprint
# skip-check (see get_or_compute_gwl_year_table and process_field in
# run.py) — an unchanged field's build is a fast no-op, not a recompute.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAX_WAIT_MINUTES=50

PROCESS_PROJECTS=(
  "ClimateImpactsProcessTas"
  "ClimateImpactsProcessPr"
  "ClimateImpactsProcessConsecutiveDryDays"
  "ClimateImpactsProcessExtremeHeatDays"
  "ClimateImpactsProcessMaize"
  "ClimateImpactsProcessSpringWheat"
  "ClimateImpactsProcessSoy"
  "ClimateImpactsProcessRice"
)

for project in "${PROCESS_PROJECTS[@]}"; do
  echo "==> Process: $project"
  "$ROOT/scripts/run-codebuild.sh" "$project" "$MAX_WAIT_MINUTES"
done

echo "==> All 8 process fields completed"
