#!/usr/bin/env bash
# Full deploy: provisions/updates the S3 + CloudFront infrastructure, then
# triggers a build on real AWS compute (CodeBuild) — this machine does not
# build the frontend. Creates/uses real, billed resources.
#
# The remote build pulls from GitHub, not local files — push your changes
# before running this, or the build will use whatever's currently on main.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/check-aws-credentials.sh"
"$ROOT/scripts/provision-infra.sh"
"$ROOT/scripts/run-codebuild.sh" "ClimateImpactsFrontendBuild"

DOMAIN=$(python3 -c "import json; print(json.load(open('$ROOT/infra/outputs.json'))['ClimateImpactsFrontendHosting']['DistributionDomainName'])")
echo "==> Live at https://$DOMAIN"
