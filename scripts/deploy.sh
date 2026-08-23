#!/usr/bin/env bash
# Full deploy: provisions/updates AWS infrastructure, builds the frontend,
# uploads it, and invalidates the cache. Creates real, billed resources.
#
# Each step below also runs standalone (see the other scripts in this
# directory) — this just chains them in order. Nothing here is
# GitHub-Actions-specific: any caller (a human, GitHub Actions, AWS
# CodeBuild) can run this whole file, or call the individual steps
# directly and handle sequencing itself.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/check-aws-credentials.sh"
"$ROOT/scripts/provision-infra.sh"
"$ROOT/scripts/build-frontend.sh"
"$ROOT/scripts/upload-frontend.sh"
"$ROOT/scripts/invalidate-cache.sh"

DOMAIN=$(python3 -c "import json; print(json.load(open('$ROOT/infra/outputs.json'))['ClimateImpactsFrontendHosting']['DistributionDomainName'])")
echo "==> Live at https://$DOMAIN"
