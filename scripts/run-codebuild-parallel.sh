#!/usr/bin/env bash
# Starts multiple CodeBuild projects at once and waits for all of them to reach
# a terminal state — real parallel execution, not sequential start-wait-start.
# Each project passed here is already fully independent (its own command
# baked in via infra/stacks/pipeline_step_build_project_stack.py, its own
# real S3 inputs/outputs) — nothing about running them together changes what
# any one of them does.
#
# Plain indexed arrays throughout, not associative arrays (declare -A):
# macOS's default /bin/bash is 3.2 (no bash 4+ features available, no
# Homebrew bash on this machine either — checked directly, not assumed).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/check-aws-credentials.sh"
if [ -z "${AWS_PROFILE:-}" ] && aws configure list-profiles 2>/dev/null | grep -qx "dev"; then
  export AWS_PROFILE="dev"
fi

MAX_WAIT_MINUTES="${MAX_WAIT_MINUTES:-50}"
PROJECTS=("$@")

if [ ${#PROJECTS[@]} -eq 0 ]; then
  echo "Usage: MAX_WAIT_MINUTES=<n> run-codebuild-parallel.sh <project-name> [<project-name> ...]" >&2
  exit 1
fi

echo "==> Starting ${#PROJECTS[@]} builds in parallel: ${PROJECTS[*]}"

BUILD_IDS=()
STATUSES=()
for project in "${PROJECTS[@]}"; do
  build_id=$(aws codebuild start-build --project-name "$project" --query 'build.id' --output text)
  BUILD_IDS+=("$build_id")
  STATUSES+=("IN_PROGRESS")
  echo "==> Started $project: $build_id"
done

MAX_CHECKS=$((MAX_WAIT_MINUTES * 6)) # 6 checks/minute at 10s intervals
CHECKS=0

while true; do
  ALL_DONE=true
  for i in "${!PROJECTS[@]}"; do
    if [ "${STATUSES[$i]}" == "IN_PROGRESS" ]; then
      st=$(aws codebuild batch-get-builds --ids "${BUILD_IDS[$i]}" --query 'builds[0].buildStatus' --output text)
      if [ "$st" != "IN_PROGRESS" ]; then
        STATUSES[$i]="$st"
        echo "==> ${PROJECTS[$i]} finished: $st"
      else
        ALL_DONE=false
      fi
    fi
  done

  if [ "$ALL_DONE" == "true" ]; then
    break
  fi

  if [ "$CHECKS" -ge "$MAX_CHECKS" ]; then
    echo "Timed out waiting for builds after $MAX_WAIT_MINUTES minutes. Status:" >&2
    for i in "${!PROJECTS[@]}"; do
      echo "  ${PROJECTS[$i]}: ${STATUSES[$i]}" >&2
    done
    exit 1
  fi

  sleep 10
  CHECKS=$((CHECKS + 1))
done

FAILED=false
for i in "${!PROJECTS[@]}"; do
  if [ "${STATUSES[$i]}" != "SUCCEEDED" ]; then
    echo "FAILED: ${PROJECTS[$i]} -> ${STATUSES[$i]}" >&2
    FAILED=true
  fi
done

if [ "$FAILED" == "true" ]; then
  exit 1
fi

echo "==> All ${#PROJECTS[@]} builds succeeded"
