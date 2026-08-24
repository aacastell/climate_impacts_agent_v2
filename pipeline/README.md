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

**`climate_pipeline/process/`** — the process stage: turns the raw NetCDF fetch already pulled
into real values for the frontend's 5 known demo regions (`regions.py` — Occitanie, Iowa,
Punjab, Nile Delta, Mekong Delta, duplicated from `frontend/src/api/mockClient.ts`'s
`KNOWN_REGIONS` since there's no shared build step between this Python pipeline and the
TypeScript frontend). Nearest-grid-cell extraction, not area-weighted — no region *boundary*
polygons exist anywhere in this repo yet for these 5 named places, only the lon/lat points
already in the mock client, so there's nothing to area-weight against (ADR-006 Step 3 describes
the eventual area-weighted design; revisit once real boundaries exist).

**This is a deliberate, temporary narrowing of ADR-006 Step 3's own reasoning.** That ADR argues
regional aggregation has to stay query-time because the region vocabulary is unbounded — true in
general, but not true yet here: there's no free-text region resolver, only these 5 hardcoded
names. Precomputing directly for a fixed 5-region set is a reasonable MVP shortcut on that basis,
not a redesign of ADR-006. It stops being valid the moment free-text region resolution exists.

Warming levels are real, not synthetic: `warming_levels.py` looks up the calendar year GFDL-ESM4
under SSP3-7.0 actually crosses each of 1.5°C, 2.0°C, and 3.0°C (source: the IPCC AR6 WGI Atlas's
own published warming-level table — read live, not recalled, same discipline as the pDSSAT
coverage check above). 4.0°C isn't reached by this model/scenario pairing within the century and
is excluded outright, not substituted with a nearby number. Each level gets its own 20-year
window centered on that crossing year — e.g. 1.5°C's window is 2031–2051 — sliced directly from
the raw driver/yield data already fetched (2026–2100 covers every window with room to spare).

**Two indicators stay synthetic for this pass: `consecutive_dry_days` and `extreme_heat_days`.**
Computing them for real needs a specific climate-index methodology (a WMO-style consecutive-dry-
day run length, a heat-day threshold in °C) that hasn't been decided anywhere in this project.
Inventing a threshold here would be exactly the kind of guess this pipeline has consistently
avoided elsewhere — these two stay mocked in the frontend until that methodology is specified.

**Yield is a single-value point estimate, not a range.** pDSSAT was already dropped for this
MVP (below), leaving only LPJmL — one crop model can't produce the two-model spread the frontend
used to display. `process/run.py` outputs one `{crop}_yield_change_pct` per window, and the
frontend's disclaimer language changed to match (single-model framing, not a fabricated range).

**`buildspec.yml`** — runs on CodeBuild, manually triggered only (no
webhook — see ADR-006 Step 7, this pipeline updates on ISIMIP/GGCMI's own
release cadence, not continuously). Bootstraps DVC fresh on every run
(`dvc init --subdir`) rather than committing `.dvc/` to git — nothing here
depends on DVC state surviving between runs, since skip-if-unchanged is
handled by the S3 checksum check above, not by a persisted `dvc.lock`.

`dvc repro` runs the whole DAG in one build, `process_regions` included — so for now, the process
stage runs on the *same* CodeBuild project as fetch (`ClimateImpactsIsimipFetch`), not a separate
one. ADR-006 explicitly leaves the process stage's compute runner as its own evaluation, separate
from fetch's — this isn't that evaluation, just the simplest thing that works before any real
profiling data exists for this stage. Splitting it onto its own project is cheap to do later if
profiling shows it needs different sizing, the same way fetch's own compute/timeout was only set
once its real volume was known.

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
else in `infra/` — `scripts/provision-infra.sh`.

### Why this runs as 5 separate builds, not one

Trigger a fetch with `scripts/run-isimip-fetch.sh` — not a single
`run-codebuild.sh` call, and not by accident. This AWS account's CodeBuild
builds are silently capped at **~45 minutes**, regardless of the project's
own configured `TimeoutInMinutes` (240, confirmed correctly deployed via the
CodeBuild API directly — this isn't a config mistake). Confirmed against
AWS's own build records, not guessed: two unrelated projects with two
different configured timeouts (240 and 60) both showed `timeoutInMinutes:
45` in their actual `StartBuild` API responses, and a real build was killed
with `BUILD_TIMED_OUT` at exactly 45:00 measured from `PROVISIONING` start —
a known, documented restriction AWS applies to new accounts on CodeBuild's
EC2 compute type (this account is 2 days old at the time this was found),
not adjustable through the project, the CLI, or the console. The only
documented fix is an AWS Support case; this works around it instead of
waiting on that.

Measured real transfer rate: ~4.3–4.5 minutes per ~2GB climate driver file,
steady, confirmed from S3 object timestamps during the build that hit the
cap. All 12 `dvc.yaml` fetch stages together need on the order of 2–2.5
hours — nowhere close to fitting in one ~45-minute build. `tas` and `pr` are
each split into their existing `baseline`/`future` stages (baseline: 3
files, ~13 min; future: 8 files, ~36 min — combining both windows into one
build measured ~47 min, just over the cap); agriculture's 8 stages are
grouped into one build since LPJmL's single-file-per-crop yield output is
far smaller than the climate driver files.

`scripts/run-isimip-fetch.sh` runs these 5 groups as 5 sequential
`start-build` calls, each overriding `DVC_TARGET` (an env var
`pipeline/buildspec.yml` passes straight to `dvc repro`) to scope that build
to its group's stages. If any one group still doesn't finish in a pass,
re-running it is always safe and cheap: the per-file S3 checksum skip-check
in `stream_to_s3.py` means already-landed files are skipped almost
instantly, not re-downloaded, so a partial group just resumes.
