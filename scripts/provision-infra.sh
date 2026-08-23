#!/usr/bin/env bash
# Provisions/updates ALL AWS infrastructure (infra/) in one pass — the S3 +
# CloudFront hosting stack and the CodeBuild project — and writes
# infra/outputs.json (each stack's outputs, keyed by stack name).
#
# One more stack later doesn't mean one more script: add it in
# infra/app.py and `cdk deploy --all` below picks it up automatically.
# CloudFormation only changes what actually differs per stack, so this is
# safe to run every time regardless of how many stacks exist or which of
# them actually changed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/check-aws-credentials.sh"
if [ -z "${AWS_PROFILE:-}" ] && aws configure list-profiles 2>/dev/null | grep -qx "dev"; then
  export AWS_PROFILE="dev"
fi

GITHUB_OWNER="${GITHUB_OWNER:-aacastell}"
GITHUB_REPO="${GITHUB_REPO:-climate_impacts_agent_v2}"

source "$HOME/.nvm/nvm.sh"
cd "$ROOT/infra"
nvm use
source venv/bin/activate

echo "==> Provisioning/updating all AWS infrastructure"
# Idempotent — a one-time per-account/region setup that cdk deploy depends
# on. Safe to run every time; no-ops if already bootstrapped.
npx aws-cdk bootstrap
npx aws-cdk deploy --all --outputs-file outputs.json \
  -c githubOwner="$GITHUB_OWNER" \
  -c githubRepo="$GITHUB_REPO"

echo "==> Wrote infra/outputs.json"
