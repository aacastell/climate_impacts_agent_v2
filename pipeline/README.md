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

**`profiling.py`** — records how long each fetch stage actually took and at
what throughput, written as a timestamped JSON record to `_profiling/` in
the same bucket (not under `raw/` — this is observability data, not a
scientific data product, and not DVC-tracked for the same reason). This
exists specifically for what CodeBuild's own build report *can't* see:
`aws codebuild batch-get-builds` gives phase-level timing for free (how
long the whole `BUILD` phase took), but all 12 fetch stages run inside that
one opaque phase — CodeBuild has no visibility into which individual stage
was slow, or what the real transfer throughput was. `stream_to_s3.py`
records per-file `duration_seconds`/`throughput_mbps` in its manifest;
`profiling.py` rolls those up into one summary per stage per run.

**S3 key layout**, so the bucket stays browsable as more scenarios/crops get
added rather than accumulating ad hoc paths:

```
raw/climate/{variable}/{scenario}/{filename}          e.g. raw/climate/tas/historical/...
raw/agriculture/{model}/{crop}/{scenario}/{filename}  e.g. raw/agriculture/lpjml/maize/ssp370/...
```

Category first (matches how the process stage will actually consume it —
"give me all `tas` data," "give me all LPJmL maize data"), then variable or
crop, then scenario as the innermost partition. Scenario names are ISIMIP's
own (`historical`, `ssp370`), not this project's `baseline`/`future` window
labels — those only name two windows; ADR-006's actual target is multiple
warming-level-anchored windows, and the path shouldn't imply there are only
ever two.

**`dvc.yaml`** — 12 fetch stages: climate drivers (`tas`, `pr`, baseline and
future windows) and all four scoped crops (maize, spring wheat, soy, rice)
from LPJmL, `noirr`, `2015soc`, baseline and future. **LPJmL only — pDSSAT is
dropped entirely for this MVP**, not a starting scope waiting to be filled
in: verified directly against ISIMIP's catalog that pDSSAT has no SSP3-7.0
output at all for GFDL-ESM4 (only `historical`, `ssp126`, `ssp585`), so it
can't contribute a future projection under this system's own climate model
and scenario. See the root README's Scope section for the accepted
consequence — no second crop model to range yield projections against,
until this is revisited post-MVP. The derived extreme-heat/dry-day
indicators are separately still follow-up work — they're not raw ISIMIP
variables fetch pulls directly; that's the process stage's job.

**Climate baseline is 1995–2014 (the last 20 years of ISIMIP's historical
record); climate future is 2026–2100.** Not the entire historical span —
that was an intermediate step, since replaced. ISIMIP only serves whole
pre-chunked decadal files, not arbitrary date ranges, so a target window
that doesn't align with ISIMIP's own chunk boundaries (1995 falls inside
the `1991_2000` file) still means fetching the whole covering file — a few
extra years ride along, trimmed later in the process stage, never at fetch.
`_files_overlapping()` in `climate.py` selects exactly the covering files
and nothing else — verified directly against the catalog: baseline pulls 3
files per variable (`1991_2000`, `2001_2010`, `2011_2014`, ~5 GB), future
pulls 8 (`2021_2030` through `2091_2100`, ~16.5 GB) — down from ~104 GB
across 54 files when the full span was fetched.

**Agriculture is unaffected by this — it was already as small as it gets.**
LPJmL yield files come as one file per crop covering the *entire* span
(1850–2014 baseline, 2015–2100 future); ISIMIP doesn't offer a smaller
pre-chunked agriculture file to select from the way it does for climate.
Trimming agriculture data to the same 1995–2014 / 2026–2100 windows happens
entirely in the process stage — there's nothing to reduce at fetch time.
**This does not yet mean the real 20-year-baseline / warming-level-anchored
windows ADR-006 describes are implemented** — that slicing is still the
process stage's job, done from this full span; fetch's job is just making
the complete span available to slice from.

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
