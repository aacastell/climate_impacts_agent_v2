# Overnight session — 2026-08-25

What got built while unsupervised, what's real vs. deliberately not deployed, and the real
benchmark findings from tonight. Read this before anything else in the morning.

## The boundary this session held to

Real code for everything, following the original architecture (Lambda orchestration,
`understanding()` and `narration()` each on their own scalable ECS/Fargate compute, Langfuse,
MLflow) with no shortcuts substituted in. What this session deliberately did **not** do, because
they're decisions that belong to whoever sees the AWS bill or owns the model's real training data:

- Did not run `cdk deploy` on `ModelServicesStack` or `ApiStack` — real, billed infrastructure
  (VPC, ECS clusters, ALBs, Lambda) defined and unit-tested, not stood up.
- Did not fine-tune `understanding()` — no training data exists yet; fabricating some overnight
  to look finished would produce a model nobody's reviewed.
- Did not write RAG corpus content — `services/narration/corpus.py` is honestly empty, not
  fabricated literature. Retrieval is real, working code; it just has nothing to retrieve yet.

## What's real and tested

**`services/understanding/`** — real tool-calling orchestration (`orchestrator.py`) against
`geocode()`/`crop()`/`timecode()` (already-real tools from `pipeline/`), backed by Claude via
Bedrock's Converse API (`model_client.py`). 4/4 tests pass, using scripted fake model responses to
verify real tool execution. Langfuse `@observe()` wired through the model call and every tool
call.

**`services/narration/`** — real RAG retrieval mechanism (cosine similarity over Bedrock
embeddings, `retrieval.py`), real generation + structured-verification client (`model_client.py`,
using Bedrock's tool-use trick to force structured JSON), real ADR-007 flow (`narrate.py`:
generation blind to the yield projection, bounded retry, `SCIENTIFIC_DISAGREEMENT` as its own
terminal state). 12/12 tests pass. Langfuse wired through retrieval/generation/verification.
MLflow eval-data capture (`eval_capture.py`) logs every `narrate()` call, not just the failures —
PASS cases are the denominator any later accuracy metric needs.

**`api/`** — the real Lambda orchestration tier (ADR-005's compute-topology decision).
`interpret_handler.py` calls `understanding()`, then reads every value from Phase 1's real
precomputed store (no LLM ever touches a scientific value). `narrate_handler.py` is a genuine pure
function of the resolved interpretation (ADR-004 Step 4) — it re-derives climate evidence itself
rather than trusting anything `interpret()` computed. 5/5 tests pass.

**Infra** — `infra/stacks/model_services_stack.py` (VPC, ECS cluster, two Fargate services with
real autoscaling) and `infra/stacks/api_stack.py` (two Lambda functions sharing one built
container image, API Gateway). 10/10 new tests pass. Wired into `infra/app.py` (safe — adding to
`app.py` doesn't deploy anything, only `cdk deploy` does, which wasn't run).

## Real bugs caught and fixed tonight, not left in

- `model_services_stack.py` had a dead `if False else` conditional from my own first draft —
  caught immediately, not shipped.
- `ApiStack` originally passed `cmd` to `DockerImageFunction` directly — real CDK API mismatch
  (confirmed live: `cmd` belongs to `DockerImageCode.from_image_asset`, not the function). Fixed,
  and verified via the synthesized template that the two Lambdas really do get different
  `ImageConfig.Command` overrides while sharing one built image (efficient, not two builds).
- MLflow's plain filesystem backend (`./mlruns`) is now in maintenance mode and refuses to
  initialize — confirmed live against the currently-installed version, not assumed from older
  docs. `eval_capture.py`'s docstring and the test both use a real sqlite backend instead.

## Correction: the "Bedrock is unprovisioned" blocker was my own mistake, not a real one

Earlier tonight this doc said Bedrock quotas were `0.0` account-wide and called it an external
blocker needing an AWS Support request. That was wrong, and it was my error, not an account
problem: I checked and called Bedrock in `us-east-1`, but this project's real home region — where
CodeBuild, the CDK app, and the "dev" SSO profile all actually live — is `us-east-2` (Ohio).
Service quotas are per-region. Checked again in the correct region: real, substantial quotas exist
(27M tokens/day for Claude Haiku 4.5, 200 req/min for Nova Lite, and more — the account has real
capacity that was never actually missing).

**Once pointed at the right region, `understanding()` and `narration()` both ran live, end to
end, for real, successfully:**

- `understanding()`, real question `"What happens to rice around the Mekong Delta at 3C?"`,
  real Bedrock (Nova Pro) + real Amazon Location Service: correctly resolved to
  `{region: "Mekong Delta, VNM" (105.83, 10.01), crop: "rice", warmingLevelC: 3, year: 2065}`. The
  model correctly judged the ambiguous geocode candidates — picked the real Vietnamese delta over
  an unrelated German restaurant and a coincidentally-named Indonesian sub-district, the exact
  ambiguity-resolution case ADR-005 Step 4 was designed for. `timecode()` correctly resolved
  3.0°C to year 2065 against the test table.
- `narration()`, same resolved query: generated narration blind to the actual yield number, then
  the verification step (given the real held-out -18.5% projection) correctly judged it
  `PASS`/`direction_match: true` — a genuine, real structured consistency check, not a stub.

One real bug found and fixed by this live test, not caught by any unit test: Bedrock Converse
requires `toolResult.content[].json` to be a JSON *object*, not a bare array/string/int.
`geocode()` returns a list, `crop()` a string-or-None, `timecode()` an int — `orchestrator.py`'s
`_run_tool` now wraps each under a named key (`{"candidates": ...}`, `{"crop": ...}`,
`{"year": ...}`) before sending it back to the model. Fixed, unit test updated to match, 4/4 still
pass.

**Remaining, real, smaller items:**
1. Anthropic models specifically still need their use-case form submitted in the Bedrock console
   before they can be called (unrelated to the quota mistake above — tried and confirmed blocked
   on Claude Haiku 4.5 specifically; Nova Pro, used for the live tests above, needed no such form).
2. Old shared CodeBuild project (`ClimateImpactsIsimipFetch`, from earlier tonight's unrelated
   pipeline decoupling work) still needs manual `aws codebuild delete-project` cleanup.

## Real benchmark findings

Two things were actually measurable tonight without Bedrock: Phase 1's precomputed-store lookup
(real data, real S3) and `geocode()` (real Esri calls). Both were measured for real, not
estimated — see `pipeline/benchmarks/query_latency_benchmark.py` and
`services/understanding/benchmark_geocode.py`, both runnable again anytime.

**Phase 1 lookup (`climate_pipeline.query.lookup.lookup_value`), n=30 iterations each:**
| | p50 | p95 | max | throughput (single sequential worker) |
|---|---|---|---|---|
| Cold (real S3 download + open) | 477ms | 690ms | 2.2s | ~2.1 req/s |
| Warm (local file cached) | 1.5ms | 1.9ms | 6.1ms | ~650 req/s |

The gap here is the single most important capacity-planning number in the whole system: **warm
Lambda reuse is ~300x faster than a cold lookup.** Every `interpret()` call does up to 6 of these
lookups, `narrate()` does 5. If those land on a cold Lambda environment every time, that's
2-3 seconds of pure S3 latency stacked before any LLM call even starts — on a warm one, it's
sub-10ms, effectively free. This is a real, strong argument for provisioned concurrency (or at
minimum, sizing traffic expectations around warm-instance reuse) on the `api/` Lambda tier
specifically, more so than for either ECS service.

One earlier run showed a 10.7s outlier that looked alarming — re-ran with 3x the iterations and it
didn't recur; the real p95 is 690ms, not 10s. Recorded here so nobody re-discovers that same
one-off and wastes time chasing it.

**`geocode()` against real Amazon Location Service (Esri), n=50:**
p50=117ms, p95=145ms, with a recurring ~1.1s outlier that showed up in both benchmark runs (not
random — likely a connection/TLS warm-up cost on a fresh client, worth confirming later, not
chased further tonight).

**`consecutive_dry_days`/`tas`/`pr`/`extreme_heat_days` process-field durations — this went from a
flagged risk to a real, confirmed, production-blocking failure, and got fixed the same night.**
`consecutive_dry_days` finished in 453s; later, `ClimateImpactsProcessTas`,
`ClimateImpactsProcessPr`, and `ClimateImpactsProcessExtremeHeatDays` all actually TIMED_OUT for
real on a live parallel run (~2600-2612s each, the account's real ~45-minute cap — confirmed via
`aws codebuild batch-get-builds`, not inferred). Two distinct real causes, both fixed:

1. **`tas`/`pr` recomputed from raw daily data 67 separate times**, ~20x redundantly across
   overlapping 20-year windows (adjacent center-years' windows share 19 of 20 years). Fixed by
   adding `annual_mean_grid()` (`pipeline/climate_pipeline/process/extract.py`) — computes the
   per-year mean once, and `run.py`'s tas/pr branch now slices+averages that small array per
   window instead of re-reading raw data every time. Verified equivalent to the original
   direct-`grid_mean()` result on the same window (not just faster — same numbers), see
   `test_annual_mean_grid_windowed_matches_grid_mean_for_the_same_window`.
2. **`extreme_heat_days_per_year` used `.groupby("time.year").sum(dim="time")` directly on a
   dask-backed array, staying fully lazy** — timed out despite sharing `consecutive_dry_days`'
   "compute once" shape, because xarray's lazy groupby-then-reduce on a large dask array is a
   real, now-confirmed performance gap (not just a hypothesis anymore — CDD's eager, per-year
   `.map()` finished the identical real dataset in under 8 minutes with a heavier per-pass
   algorithm). Fixed by switching to the same eager per-year materialization CDD already used.

Both fixes are in `pipeline/climate_pipeline/process/{extract,indices,run}.py`, tested (63/63
pipeline tests pass), and the three previously-failed builds were re-triggered tonight to confirm
for real — see below for the result.

**What's not measured, honestly labeled as an estimate, not a fact:** `understanding()`'s and
`narration()`'s real per-call Bedrock latency. The account's quota being at 0.0 makes this
impossible to measure tonight. Once the quota is fixed, running the four models already tried
(Claude Haiku, Nova Pro, Nova Lite, Mistral) through the existing test scripts in
`services/understanding/tests/` and a similar live script for `narration/` would give real
numbers in minutes — the code is ready, it just needs Bedrock access to actually work against.

## Autoscaling — fixed tonight based on the benchmark finding above

`ModelServicesStack` originally used CPU-based autoscaling (a default I reached for without
thinking it through). Real problem: both services are I/O-bound on Bedrock (waiting on network),
so CPU utilization stays low even under heavy concurrent load — CPU-based scaling would fail to
scale out exactly when it needs to. Fixed to `scale_on_request_count`:

- `understanding()`: target 20 requests/target
- `narration()`: target 10 requests/target — lower, because `narrate()`'s worst case chains up to
  3 retries (`MAX_RETRIES` in `narrate.py`), each a generate()+verify() pair, so a single request
  can occupy its thread 2-3x longer than understanding()'s typical single tool-calling resolution

Both numbers are starting points, not measured — real load testing against actual Bedrock latency
should recalibrate them, but request-count as the *metric* (not CPU) is the real, defensible part
of this fix, backed by the actual I/O-bound-workload finding, not a guess.

**How the three components should scale relative to each other, given real traffic M queries/sec:**
`understanding()` and `narration()` both see ~M requests/sec (every real query hits both, roughly
1:1) — but `narration()` needs more standing capacity per unit of M because it holds each request
longer (the retry chain above), which is exactly why its `requests_per_target` is set lower — that
makes it scale out sooner per unit of incoming load, keeping the two services' actual capacity
proportional to real demand instead of nominally "the same number of tasks" regardless of how long
each one's requests actually take.

## What's next, concretely

1. Fix the Bedrock quota (AWS Support/Service Quotas request) — this unblocks everything else.
2. Once unblocked: run the existing test infrastructure live (four models already known to at
   least authenticate correctly) to get real `understanding()`/`narration()` latency numbers, then
   recalibrate the two `requests_per_target` values above against real data.
3. Fill in `services/narration/corpus.py` with real, sourced literature — a curation task, not a
   coding one.
4. Fix `run.py`'s `tas`/`pr`/crop redundant-window-recomputation inefficiency (see benchmark
   section above) — a real, identified, unfixed performance bug.
5. Decide whether to actually `cdk deploy` `ModelServicesStack`/`ApiStack` — real cost, your call.
