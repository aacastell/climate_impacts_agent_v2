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

PROJECT_NAME="${1:?Usage: run-codebuild.sh <codebuild-project-name>}"

echo "==> Starting CodeBuild run for $PROJECT_NAME (builds main on GitHub, not local files)"
BUILD_ID=$(aws codebuild start-build --project-name "$PROJECT_NAME" --query 'build.id' --output text)
echo "==> Build started: $BUILD_ID"

MAX_CHECKS=180 # 180 * 10s = 30 minutes
CHECKS=0
STATUS="IN_PROGRESS"
while [ "$STATUS" == "IN_PROGRESS" ]; do
  if [ "$CHECKS" -ge "$MAX_CHECKS" ]; then
    echo "Timed out waiting for build $BUILD_ID after 30 minutes." >&2
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
