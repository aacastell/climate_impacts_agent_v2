# Pipeline

The offline scientific data pipeline, per [ADR-006](../docs/adr/adr-006-offline-scientific-data-pipeline.md).

## What's here

**`climate_pipeline/fetch/`** — the fetch stage. Queries ISIMIP's public API
(`isimip_client.py`) for a file's metadata, then streams it directly into S3
(`stream_to_s3.py`) — the payload is never written whole to local disk, and
never routed through DVC's own cache; DVC tracks a small manifest instead
(`manifest.py`). See ADR-006 Step 8 for the full reasoning.

Before streaming anything, `stream_to_s3.py` checks whether the target S3
key already holds this exact file (verified against ISIMIP's current
checksum, stored as S3 object metadata from the prior fetch) and skips the
download entirely if so. This isn't optional — unlike the frontend build,
which re-runs unconditionally because it's cheap, re-fetching multi-gigabyte
ISIMIP files on every CodeBuild run regardless of whether anything changed
would be a real, avoidable cost.

**`dvc.yaml`** — the fetch stages: climate drivers (`tas`, `pr`, baseline and
future windows) and agriculture (LPJmL maize, `noirr`, `2015soc`). This is a
starting scope, not the complete indicator set ADR-006 eventually needs —
pDSSAT (the second crop model the root README's "range, never a mean"
convention requires), the other three crops, and the derived extreme-heat/
dry-day indicators are follow-up work, not silently dropped.

**`buildspec.yml`** — runs on CodeBuild, manually triggered only (no
webhook — see ADR-006 Step 7, this pipeline updates on ISIMIP/GGCMI's own
release cadence, not continuously). Bootstraps DVC fresh on every run
(`dvc init --subdir`) rather than committing `.dvc/` to git — nothing here
depends on DVC state surviving between runs, since skip-if-unchanged is
handled by the S3 checksum check above, not by a persisted `dvc.lock`.

## Local setup (code changes only — never for running fetch against real data)

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

Every test here mocks S3 and the ISIMIP HTTP client — no real network calls,
no real data. **Nothing in this directory downloads real ISIMIP data
locally, ever, by design** — that only happens inside the CodeBuild project
provisioned by `infra/stacks/isimip_fetch_build_project_stack.py`, triggered
via `scripts/run-codebuild.sh <project-name>`.

## Deploying and running

The bucket and CodeBuild project are provisioned the same way as everything
else in `infra/` — `scripts/provision-infra.sh`. Once deployed, trigger a
fetch with `scripts/run-codebuild.sh <the fetch project's name>` (see
`infra/outputs.json` after provisioning for the exact name).
