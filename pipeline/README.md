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
record); climate future is 2015–2100.** Not the entire historical span —
that was an intermediate step, since replaced. ISIMIP only serves whole
pre-chunked decadal files, not arbitrary date ranges, so a target window
that doesn't align with ISIMIP's own chunk boundaries (1995 falls inside
the `1991_2000` file) still means fetching the whole covering file — a few
extra years ride along, trimmed later in the process stage, never at fetch.
`_files_overlapping()` in `climate.py` selects exactly the covering files
and nothing else — verified directly against the catalog: baseline pulls 3
files per variable (`1991_2000`, `2001_2010`, `2011_2014`, ~5 GB), future
pulls 9 (`2015_2020` through `2091_2100`, ~17.7 GB).

Future starts at 2015, not 2026: the process stage's target design computes
a global warming level for *every* year via a 20-year window centered on
it (the same methodology IPCC AR6's Atlas uses), not just a few fixed
checkpoints — centering on year Y needs data back to Y-10, so 2015 as the
earliest fetched year makes ~2025+ the earliest usable center year. This
widening only cost ~2.5 GB in practice (one new `2015_2020` file per
variable) — the per-file S3 skip-check meant the other 8 already-fetched
future files and all 3 baseline files were skipped, not re-downloaded.

**`fetch_tas_preindustrial`** (tas only) fetches 1850–1900 — the IPCC
standard preindustrial reference period global warming levels are measured
against, *not* ISIMIP's own separate "preindustrial scenario" (that's
1601–1849, a different thing used for model-drift control runs). 1850–1900
is simply the start of ISIMIP's own `historical` GFDL-ESM4 dataset
(verified live: the earliest file is `..._historical_tas_..._1850_1850.nc`)
— reusing the exact same dataset and bias-adjustment pipeline as this
project's own baseline, just an earlier year-slice of it, rather than
importing a preindustrial number from elsewhere and risking a mismatched
bias-adjustment. 6 files, ~10.5 GB (`1850_1850` through `1891_1900`). pr
has no preindustrial-GWL concept — GWL is a temperature-only definition —
so this window is tas-only, enforced in code (`climate.py` raises if asked
to fetch it for `pr`), not just documented.

**Agriculture is unaffected by this — it was already as small as it gets.**
LPJmL yield files come as one file per crop covering the *entire* span
(1850–2014 baseline, 2015–2100 future); ISIMIP doesn't offer a smaller
pre-chunked agriculture file to select from the way it does for climate.
Trimming agriculture data to the same 1995–2014 / 2015–2100 windows happens
entirely in the process stage — there's nothing to reduce at fetch time.
**This does not yet mean the real 20-year-baseline / warming-level-anchored
windows ADR-006 describes are implemented** — that slicing is still the
process stage's job, done from this full span; fetch's job is just making
the complete span available to slice from.

**`climate_pipeline/process/`** — the process stage: turns the raw NetCDF fetch already pulled
into the real **global** precomputed grid. Supersedes an earlier 5-fixed-point MVP (nearest-cell
extraction for 5 hardcoded demo regions) — that version is gone; regional extraction is
explicitly out of scope for this stage now, deferred to whatever query-time API eventually reads
from this output (ADR-006 Step 3: regional aggregation stays query-time because the region
vocabulary is unbounded — this stage no longer narrows that down to 5 names).

**Only change-from-baseline gets stored — baseline (1995–2014) itself is intermediate, never a
persisted output.** For every field (`tas`, `pr`, `consecutive_dry_days`, `extreme_heat_days`,
and each of the 4 crops' yield), the stored value is `window - baseline` (absolute °C for `tas`
and the two day-count indices, % for `pr` and yield) — never the raw window or baseline mean on
its own.

**Global warming level (GWL) is self-computed, not looked up from a fixed table.** For every year
Y from 2025 to 2091 (67 years — bounded by the real fetched future span, 2015–2100, and a 20-year
window `[Y-10, Y+9]` needing to fit entirely inside it), the area-weighted global mean `tas` over
that window, minus the preindustrial reference, *is* GWL(Y) — it falls out of the same
computation the per-cell change grids already need, not a separate lookup. The preindustrial
reference (1850–1900, the IPCC standard) is real ISIMIP data, not an external number: it's simply
the start of the same `historical` GFDL-ESM4 dataset this project's own baseline already comes
from (verified live — the earliest file is `..._historical_tas_global_daily_1850_1850.nc`),
fetched via `fetch_tas_preindustrial`. An earlier pass in this project used a 3-checkpoint table
from the IPCC AR6 Atlas (1.5°C/2.0°C/3.0°C only) — that's gone too, replaced by this per-year
computation.

**`consecutive_dry_days` and `extreme_heat_days` are real now, not synthetic.** Dry days use the
ETCCDI CDD standard (longest run of consecutive days with precip < 1mm within a calendar year) —
a real, still-widely-used index despite the ETCCDI program itself having ended in 2018. Extreme
heat uses a 35°C threshold — a single global value, not crop-specific, a deliberate documented
tradeoff (empirical crop-specific thresholds, e.g. ~34.8°C for maize, are more scientifically
defensible per current literature, but would need a credible sourced number per crop and
quadruple storage; 35°C is the more standard of the two commonly-cited round-number thresholds).
Both are computed per calendar year first, then averaged across each 20-year window — see
`process/indices.py`.

**Not every field gets a single output — some get two.** Percent change is only valid for
continuous, ratio-scale quantities with a true zero where it's the domain-conventional framing
(`pr`, yield) — invalid for temperature (no true zero) and misleading for the two day-count
indices (near-zero baselines are common and produce meaningless swings). Where percent *is*
valid, both absolute and percent are stored, not one chosen on the data's behalf — a
small-baseline cell (arid precip, marginal cropland) can make percent change technically correct
but misleading, so the choice is left to whatever consumes this later rather than picked here.
`tas`/`consecutive_dry_days`/`extreme_heat_days` write one field each (bare name); `pr` and each
of the 4 crops write two (`{field}_abs`, `{field}_pct`) — see `run.py`'s `FIELD_VARIANTS`.

**Storage: one small NetCDF object per (field-variant, window), not one large array.** 67 windows
× 13 field-variants (3 single + 5 doubled) = 871 objects, each ~1MB (a single 720×360 grid) →
~871MB total. This layout is why the canonical store's format doesn't need Zarr's
chunked-partial-read sophistication (worked through via a real local benchmark, not assumed) —
every object is already small enough that downloading it whole, in any reasonably convenient
format, is fast regardless of chunking. Output keys: `processed/global/{field}/y{year}.nc`, plus
`processed/global/manifest.json` listing every object's `{field, kind, year, gwl_c}` so a future
query-time consumer can find the right key directly.

**`buildspec.yml`** — runs on CodeBuild, manually triggered only (no
webhook — see ADR-006 Step 7, this pipeline updates on ISIMIP/GGCMI's own
release cadence, not continuously). Bootstraps DVC fresh on every run
(`dvc init --subdir`) rather than committing `.dvc/` to git — nothing here
depends on DVC state surviving between runs, since skip-if-unchanged is
handled by the S3 checksum check above, not by a persisted `dvc.lock`.

`dvc repro` runs the whole DAG in one build, `process_global` included — so for now, the process
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
