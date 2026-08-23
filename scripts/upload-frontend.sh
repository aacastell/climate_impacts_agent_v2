#!/usr/bin/env bash
# Uploads frontend/dist/ to the S3 bucket named in infra/outputs.json.
# Hashed assets first, index.html last — see ADR-001 on why the order
# matters: index.html must never reference a bundle that isn't there yet.
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

if [ ! -d "$ROOT/frontend/dist" ]; then
  echo "No frontend/dist found. Run scripts/build-frontend.sh first." >&2
  exit 1
fi

BUCKET=$(python3 -c "import json; print(json.load(open('$OUTPUTS'))['ClimateImpactsFrontendHosting']['BucketName'])")

echo "==> Uploading to s3://$BUCKET (hashed assets first, index.html last)"
aws s3 sync "$ROOT/frontend/dist/" "s3://$BUCKET" --delete --exclude index.html
aws s3 cp "$ROOT/frontend/dist/index.html" "s3://$BUCKET/index.html" --cache-control "no-cache"
