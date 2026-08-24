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
# 235 min wait, just under the CodeBuild project's own 4-hour timeout
# (infra/stacks/isimip_fetch_build_project_stack.py) — real transfer
# volume here is tens of GB, untested at the time this was set; the
# default 30-minute wait (fine for the frontend build) would very likely
# time out this script before CodeBuild itself does.
"$ROOT/scripts/run-codebuild.sh" "ClimateImpactsIsimipFetch" 235

DOMAIN=$(python3 -c "import json; print(json.load(open('$ROOT/infra/outputs.json'))['ClimateImpactsFrontendHosting']['DistributionDomainName'])")
echo "==> Live at https://$DOMAIN"
