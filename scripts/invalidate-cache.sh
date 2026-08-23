#!/usr/bin/env bash
# Invalidates CloudFront's cached index.html so a new deploy is visible
# immediately, instead of waiting for edge caches to expire on their own.
# Only index.html needs this — the hashed JS/CSS filenames change whenever
# their content does, so a stale cached copy of one is never wrong.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/check-aws-credentials.sh"
if [ -z "${AWS_PROFILE:-}" ] && aws configure list-profiles 2>/dev/null | grep -qx "dev"; then
  export AWS_PROFILE="dev"
fi

# CodeBuild has this baked in as an environment variable (see
# frontend_build_project_stack.py) — infra/outputs.json is gitignored and
# never reaches its fresh checkout. Fall back to it for local/human use,
# where provision-infra.sh already wrote it on this same machine.
if [ -n "${FRONTEND_DISTRIBUTION_ID:-}" ]; then
  DISTRIBUTION_ID="$FRONTEND_DISTRIBUTION_ID"
else
  OUTPUTS="$ROOT/infra/outputs.json"
  if [ ! -f "$OUTPUTS" ]; then
    echo "No infra/outputs.json found and FRONTEND_DISTRIBUTION_ID not set. Run scripts/provision-infra.sh first." >&2
    exit 1
  fi
  DISTRIBUTION_ID=$(python3 -c "import json; print(json.load(open('$OUTPUTS'))['ClimateImpactsFrontendHosting']['DistributionId'])")
fi

echo "==> Invalidating CloudFront cache"
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" --paths "/index.html" "/" >/dev/null
