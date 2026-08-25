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
# 13 fully independent CodeBuild projects, one per fetch stage — not one shared project with
# parameterized triggers. See scripts/run-isimip-fetch.sh and
# infra/stacks/pipeline_step_build_project_stack.py.
"$ROOT/scripts/run-isimip-fetch.sh"
# 8 fully independent CodeBuild projects, one per process field — same separation, same reason.
# See scripts/run-process-fields.sh.
"$ROOT/scripts/run-process-fields.sh"

DOMAIN=$(python3 -c "import json; print(json.load(open('$ROOT/infra/outputs.json'))['ClimateImpactsFrontendHosting']['DistributionDomainName'])")
echo "==> Live at https://$DOMAIN"
