#!/usr/bin/env bash
# Full deploy: provisions/updates all AWS infrastructure (frontend hosting
# and the ISIMIP data pipeline), then triggers both CodeBuild projects —
# this machine does not build the frontend or fetch ISIMIP data itself.
# Creates/uses real, billed resources.
#
# The ISIMIP fetch is safe to run unconditionally here, unlike a naive
# "just re-download everything": stream_to_s3.py checks S3 before pulling
# anything, so a fetch with nothing new to fetch costs a handful of cheap
# HEAD requests, not a re-download. See pipeline/README.md and ADR-006.
#
# Both remote builds pull from GitHub, not local files — push your changes
# before running this, or they'll use whatever's currently on main.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

"$ROOT/scripts/check-aws-credentials.sh"
"$ROOT/scripts/provision-infra.sh"
"$ROOT/scripts/run-codebuild.sh" "ClimateImpactsFrontendBuild"
# Runs as 5 separate CodeBuild builds, not one call here — this account's
# CodeBuild builds are capped at ~45 minutes regardless of the project's own
# configured timeout, well under what one build covering all 12 fetch
# stages needs. See scripts/run-isimip-fetch.sh and pipeline/README.md.
"$ROOT/scripts/run-isimip-fetch.sh"

DOMAIN=$(python3 -c "import json; print(json.load(open('$ROOT/infra/outputs.json'))['ClimateImpactsFrontendHosting']['DistributionDomainName'])")
echo "==> Live at https://$DOMAIN"
