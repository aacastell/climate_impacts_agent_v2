#!/usr/bin/env bash
# Runs all 8 process fields plus the dedicated GWL-table step in parallel —
# each its own fully independent CodeBuild project (see
# infra/stacks/pipeline_step_build_project_stack.py and
# infra/app.py's PROCESS_STEPS), command baked in at the project level.
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
# None of the 8 fields know or care about global warming level — GWL is
# resolved separately, in its own step (climate_pipeline/process/gwl_table.py),
# only at query time. No ordering dependency between the table and the 8
# fields: all 9 only depend on fetch having completed, nothing on each
# other, so all 9 run in the same wave.
#
# 9 concurrent builds, comfortably under this account's real, checked
# concurrent-build limit for the Linux/Medium environment (15 — confirmed
# via `aws service-quotas`). Must run after run-isimip-fetch.sh completes —
# a real data dependency (each downloads fetch's manifests directly from
# S3), not an artificial ordering choice.
#
# Safe to re-run: each field has its own whole-run input-fingerprint
# skip-check (process_field in run.py) — an unchanged field's build is a
# fast no-op, not a recompute. The GWL table's own skip-check is a plain
# existence check (gwl_table.py) — it's tas-derived only and never changes
# once computed for a given tas dataset.
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
  "ClimateImpactsProcessGwlYearTable"
)

MAX_WAIT_MINUTES="$MAX_WAIT_MINUTES" "$ROOT/scripts/run-codebuild-parallel.sh" "${PROCESS_PROJECTS[@]}"

echo "==> All 9 process steps completed"
