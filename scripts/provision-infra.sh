#!/usr/bin/env bash
# Provisions/updates the S3 + CloudFront infrastructure (infra/) and writes
# infra/outputs.json — the bucket name, distribution ID, and domain that
# upload-frontend.sh and invalidate-cache.sh read afterward.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/check-aws-credentials.sh"
if [ -z "${AWS_PROFILE:-}" ] && aws configure list-profiles 2>/dev/null | grep -qx "dev"; then
  export AWS_PROFILE="dev"
fi

source "$HOME/.nvm/nvm.sh"
cd "$ROOT/infra"
nvm use
source venv/bin/activate

echo "==> Provisioning/updating AWS infrastructure"
# Idempotent — a one-time per-account/region setup that cdk deploy depends
# on. Safe to run every time; no-ops if already bootstrapped.
npx aws-cdk bootstrap
npx aws-cdk deploy --outputs-file outputs.json

echo "==> Wrote infra/outputs.json"
