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

OUTPUTS="$ROOT/infra/outputs.json"
if [ ! -f "$OUTPUTS" ]; then
  echo "No infra/outputs.json found. Run scripts/provision-infra.sh first." >&2
  exit 1
fi

DISTRIBUTION_ID=$(python3 -c "import json; print(json.load(open('$OUTPUTS'))['ClimateImpactsFrontendHosting']['DistributionId'])")

echo "==> Invalidating CloudFront cache"
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" --paths "/index.html" "/" >/dev/null
