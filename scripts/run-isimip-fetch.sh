#!/usr/bin/env bash
# Runs the ISIMIP fetch pipeline as 5 separate CodeBuild builds instead of
# one — see pipeline/README.md ("Why this runs as 5 separate builds, not
# one"). This account's CodeBuild builds are silently capped to ~45 minutes
# regardless of the project's own configured timeout (confirmed against AWS's
# own build records, not a guess — see that section); a single build
# covering all 12 dvc.yaml fetch stages needs ~2-2.5 hours at this data's
# measured transfer rate, so it never finishes in one pass under that cap.
#
# Each group here is sized, from real measured per-file throughput, to
# finish comfortably inside ~45 minutes. If one still doesn't finish, it's
# safe to just re-run this script: the per-file S3 checksum skip-check in
# stream_to_s3.py means already-fetched files are skipped almost instantly,
# not re-downloaded, so a partial group just resumes from where it stopped.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_NAME="ClimateImpactsIsimipFetch"
# 50 min: comfortably past each group's expected ~45-min ceiling, so this
# script observes whichever terminal status CodeBuild actually reaches
# (SUCCEEDED or the account-level TIMED_OUT) instead of giving up first.
MAX_WAIT_MINUTES=50

# tas/pr baseline (3 files, ~2GB each, ~13 min) and future (8 files, ~36
# min) are kept separate — combined, either variable's two windows together
# measured ~47 min, over the cap. Agriculture's 8 stages are one LPJmL
# output file each, far smaller than the climate driver files, so they're
# grouped into a single build.
#
# Named FETCH_GROUPS, not GROUPS: `GROUPS` is a bash builtin special
# variable (the current user's real UNIX group IDs, like $UID/$PPID) —
# assigning to it is a silent no-op, so a loop over "${GROUPS[@]}" was
# actually iterating the real system group list, not this array, and every
# `run-codebuild.sh` call got the first real GID (e.g. 20) as DVC_TARGET
# instead of a stage name. Confirmed against `id -G` — exact match.
FETCH_GROUPS=(
  "fetch_tas_baseline"
  "fetch_tas_future"
  "fetch_pr_baseline"
  "fetch_pr_future"
  "fetch_agriculture_maize_baseline fetch_agriculture_maize_future fetch_agriculture_spring_wheat_baseline fetch_agriculture_spring_wheat_future fetch_agriculture_soy_baseline fetch_agriculture_soy_future fetch_agriculture_rice_baseline fetch_agriculture_rice_future"
)

for group in "${FETCH_GROUPS[@]}"; do
  echo "==> Fetch group: $group"
  "$ROOT/scripts/run-codebuild.sh" "$PROJECT_NAME" "$MAX_WAIT_MINUTES" "$group"
done

echo "==> All ISIMIP fetch groups completed"
