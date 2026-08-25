#!/usr/bin/env bash
# Starts a build on the given CodeBuild project — real, ephemeral AWS
# compute, not this machine — and waits for it to finish. The build itself
# runs build-frontend.sh, upload-frontend.sh, and invalidate-cache.sh
# remotely (see ../frontend/buildspec.yml); this script's only local work is
# starting it and polling for the result.
#
# Builds whatever is currently on the project's configured branch (main)
# on GitHub — not your local working directory. Push before running this.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/check-aws-credentials.sh"
if [ -z "${AWS_PROFILE:-}" ] && aws configure list-profiles 2>/dev/null | grep -qx "dev"; then
  export AWS_PROFILE="dev"
fi

PROJECT_NAME="${1:?Usage: run-codebuild.sh <codebuild-project-name> [max-wait-minutes] [run-cmd-override]}"
# Default (30 min) fits the frontend build, which should fail fast if
# something's wrong. Long-running builds (e.g. an ISIMIP fetch stage, real
# transfer volume in the tens of GB) need a longer wait explicitly passed
# as the second argument — this script has no way to know a project's
# expected duration on its own.
MAX_WAIT_MINUTES="${2:-30}"
# Optional: overrides RUN_CMD for this one build only — a direct
# `python -m climate_pipeline...` invocation, never `dvc repro` (see
# pipeline/buildspec.yml and pipeline/climate_pipeline/process/run.py's
# module docstring for why `dvc repro` was dropped from CI entirely: every
# fetch/process stage is now a fully independent unit, and routing through
# DVC's dependency graph caused one stage's build to silently re-run
# unrelated upstream stages, since dvc.lock is never committed to git).
RUN_CMD_OVERRIDE="${3:-}"

echo "==> Starting CodeBuild run for $PROJECT_NAME (builds main on GitHub, not local files)"
if [ -n "$RUN_CMD_OVERRIDE" ]; then
  echo "==> RUN_CMD: $RUN_CMD_OVERRIDE"
  # JSON, not shorthand syntax: the value is an arbitrary command string with
  # spaces/flags, and shorthand's comma-delimited field parsing is the wrong
  # tool for a value that isn't a single simple token.
  ENV_OVERRIDE_JSON=$(python3 -c "import json,sys; print(json.dumps([{'name': 'RUN_CMD', 'value': sys.argv[1], 'type': 'PLAINTEXT'}]))" "$RUN_CMD_OVERRIDE")
  BUILD_ID=$(aws codebuild start-build --project-name "$PROJECT_NAME" \
    --environment-variables-override "$ENV_OVERRIDE_JSON" \
    --query 'build.id' --output text)
else
  BUILD_ID=$(aws codebuild start-build --project-name "$PROJECT_NAME" --query 'build.id' --output text)
fi
echo "==> Build started: $BUILD_ID"

MAX_CHECKS=$((MAX_WAIT_MINUTES * 6)) # 6 checks/minute at 10s intervals
CHECKS=0
STATUS="IN_PROGRESS"
while [ "$STATUS" == "IN_PROGRESS" ]; do
  if [ "$CHECKS" -ge "$MAX_CHECKS" ]; then
    echo "Timed out waiting for build $BUILD_ID after $MAX_WAIT_MINUTES minutes." >&2
    exit 1
  fi
  sleep 10
  CHECKS=$((CHECKS + 1))
  STATUS=$(aws codebuild batch-get-builds --ids "$BUILD_ID" --query 'builds[0].buildStatus' --output text)
  echo "==> Status: $STATUS (${CHECKS}0s elapsed)"
done

if [ "$STATUS" != "SUCCEEDED" ]; then
  echo "Build failed with status: $STATUS" >&2
  echo "Logs: https://${AWS_REGION:-us-east-2}.console.aws.amazon.com/codesuite/codebuild/projects/$PROJECT_NAME/build/$BUILD_ID/log" >&2
  exit 1
fi

echo "==> Build succeeded"
