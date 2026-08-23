#!/usr/bin/env bash
# Uploads frontend/dist/ to the hosting bucket. Hashed assets first,
# index.html last — see ADR-001 on why the order matters: index.html must
# never reference a bundle that isn't there yet.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/check-aws-credentials.sh"
if [ -z "${AWS_PROFILE:-}" ] && aws configure list-profiles 2>/dev/null | grep -qx "dev"; then
  export AWS_PROFILE="dev"
fi

if [ ! -d "$ROOT/frontend/dist" ]; then
  echo "No frontend/dist found. Run scripts/build-frontend.sh first." >&2
  exit 1
fi

# CodeBuild has this baked in as an environment variable (see
# frontend_build_project_stack.py) — infra/outputs.json is gitignored and
# never reaches its fresh checkout. Fall back to it for local/human use,
# where provision-infra.sh already wrote it on this same machine.
if [ -n "${FRONTEND_BUCKET_NAME:-}" ]; then
  BUCKET="$FRONTEND_BUCKET_NAME"
else
  OUTPUTS="$ROOT/infra/outputs.json"
  if [ ! -f "$OUTPUTS" ]; then
    echo "No infra/outputs.json found and FRONTEND_BUCKET_NAME not set. Run scripts/provision-infra.sh first." >&2
    exit 1
  fi
  BUCKET=$(python3 -c "import json; print(json.load(open('$OUTPUTS'))['ClimateImpactsFrontendHosting']['BucketName'])")
fi

echo "==> Uploading to s3://$BUCKET (hashed assets first, index.html last)"
aws s3 sync "$ROOT/frontend/dist/" "s3://$BUCKET" --delete --exclude index.html
aws s3 cp "$ROOT/frontend/dist/index.html" "s3://$BUCKET/index.html" --cache-control "no-cache"
