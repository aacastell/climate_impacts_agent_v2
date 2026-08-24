# ADR-006: Offline Scientific Data Pipeline

**Status:** Accepted
**Depends on:** ADR-004 (map data delivery) — this ADR generalizes ADR-004's precompute decision
from map-shading data specifically to every expensive scientific calculation the system needs.
**Informs:** ADR-007 (narration verification gate) — supplies the held-out yield projection.
**Scope:** How raw ISIMIP/GGCMI data becomes the canonical precomputed grids the scientific
query layer and map products both consume. Does not cover canonical storage format (Zarr is a
candidate, unproven), the pipeline's compute runner (CodeBuild vs. ECS/Batch), or backend
query-time compute topology.

---

## Context

ADR-004 decided that map-shading data is precomputed once, offline, and served as static files —
never computed per query. The conceptual design this ADR records generalizes that same argument
to every expensive scientific calculation the system needs, not just what ends up shaded on a
map: baseline computation, and driver and yield change relative to that baseline. That's a
broader claim than ADR-004 made, with its own reasoning about exactly where the precompute/
query-time boundary sits — which is why it gets its own ADR rather than being folded into
ADR-004 after the fact.

---

## Decision

**ISIMIP/GGCMI raw NetCDF flows through a DVC-tracked pipeline that produces canonical global
precomputed grids: a fixed 20-year baseline, sliding 20-year windows anchored to warming levels,
and baseline-relative change for both climate drivers and crop yields — computed once, globally,
offline.** Regional aggregation (spatial mask + weighted statistics for whatever region a query
resolves to) happens at query time, not precomputed, because it is cheap and inherently
region-dependent. Counterfactual questions ("what if warming had been limited to 1.5°C") are
kept as planned, not implemented.

---

## How we got there

### Step 1 — Does ADR-004's precompute argument actually generalize?

Yes, and for the identical reason. ADR-004's Step 1 argument was: the option space (indicator ×
warming level × crop model) is bounded and known in advance, independent of any question a user
happens to ask — recomputing a slice of it per request is redundant against a fixed,
precomputable space. Nothing in that argument was specific to shading data; it applies equally
to baseline statistics and driver/yield changes. Restricting precompute to "whatever happens to
render on a map" would have been an arbitrary scope cut with no principled reason behind it.

### Step 2 — Why a fixed 20-year baseline, and why sliding windows anchored to warming levels?

A fixed baseline gives every warming-level comparison a stable reference point. If the baseline
itself moved, "change relative to baseline" would mean something different depending on which
warming level was being compared, making cross-warming-level comparisons unreliable. Windows are
anchored to warming levels rather than calendar years because different scenarios and models
cross a given warming level at different calendar times — anchoring to the year would silently
conflate "when" with "how much warming," which is precisely the kind of confusion the repo
root README already warns about for `2015soc` and single-model uncertainty. Anchoring to the
warming level itself keeps the comparison honest.

### Step 3 — Where exactly is the precompute / query-time boundary?

Regional aggregation is the one calculation deliberately left at query time, and for a different
reason than "it's fast": the set of regions a user might name is effectively unbounded — any
place name, at any scale, is a valid query. Indicator × warming level × crop model is a small,
enumerable set; regions are not. Precomputing per-region statistics would require either
restricting the region vocabulary in advance (which contradicts the product's own free-text
query design) or precomputing for an unbounded space, which isn't possible. Spatial masking and
weighted statistics against the already-precomputed global grid are cheap enough to run live,
per query, against whatever region actually gets resolved.

Grid cells on a lat/lon grid do not have equal area, so a naive unweighted mean across cells
would silently misweight the result. The candidate approach is an area-weighted mean — cell
value weighted by cell area, with fractional cell coverage as a further refinement for regions
whose boundary cuts through a cell rather than aligning with grid lines. This is recorded here as
the leading candidate, not a locked method: the exact regional-statistics package (mean, median,
std, min/max, percentiles, and whether area weighting or fractional coverage is actually needed
at this grid's resolution) still belongs in the scientific specification, not this ADR.

### Step 4 — Counterfactual questions: why deferred, not built?

Kept as planned, not implemented. Supporting "what if warming had been limited to X" is a
distinct scope decision requiring its own scientific validation — which counterfactual scenarios
are even meaningful to answer, and what data supports them — orthogonal to this pipeline's
architecture. Building the pipeline to speculatively support it now, before that scope question
is settled, would be exactly the kind of premature generalization this project avoids elsewhere
(see ADR-001's rejection of inventing a WAF shape before rate-limit rules were decided).

### Step 5 — Why not Airflow to orchestrate this pipeline?

Rejected for now, not on technical merit. DVC already gives this pipeline what it actually needs
today — dependency tracking between raw data, intermediate products, and final grids. Airflow is
a scheduler/orchestrator built for recurring, complex, multi-system workflows; this pipeline
isn't that yet. Revisit if it grows enough recurring cross-system complexity that DVC's
dependency-graph model stops being sufficient on its own.

### Step 6 — Why not Kubeflow?

Same shape of rejection, stated plainly in the original design notes: no Kubeflow just because
ML systems use Kubeflow. There is no training loop in this system yet — this pipeline is
deterministic precompute, not model training. Introduce it when the ML lifecycle (not this
pipeline) actually becomes complex enough to need it, not preemptively.

### Step 7 — What actually triggers a new pipeline run?

Not continuous polling. ISIMIP itself is relatively stable — new experiments and results arrive
on long timescales, not daily — and GGCMI is the more likely source of frequent updates, but
still nowhere near a pace that justifies watching for changes automatically. Building a polling
architecture now would be solving a problem this data doesn't have, on the same "production
systems are supposed to do X" reasoning this ADR already rejects for Airflow and Kubeflow. The
lifecycle instead: a new experiment or data version is identified (manually, by whoever's
tracking ISIMIP/GGCMI releases) → the pipeline's data-version configuration is updated → the
pipeline is triggered → `dvc repro` runs → new derived products are published under a new
version. The exact trigger mechanism — who runs it, whether it's a manual command or a
lightweight scheduled check — is left to implementation.

---

## Accompanying decisions

- **Canonical storage format is deliberately left open.** Zarr is a candidate, but unproven
  against this system's actual access pattern (global grid, sliced by region and indicator at
  query time). Deciding this now, ahead of testing it against real access patterns, would
  misrepresent an untested guess as a settled architectural decision.
- **The canonical scientific format and the frontend's map-delivery format are not assumed to be
  the same file.** The backend's access pattern is arbitrary-cell lookup for regional statistics;
  the frontend's (ADR-004) is tiles/pixels for shading a map — genuinely different consumption
  patterns with no reason to force one representation to serve both. The expected shape is a
  canonical store (Zarr or otherwise) that map-asset generation reads *from* to produce whatever
  ADR-004's delivery format turns out to be (COG, tiles, or otherwise), not one file serving both
  paths directly. Both formats remain open; only the "they don't have to match" relationship
  between them is decided here.
- **CodeBuild is not assumed as this pipeline's compute runner, despite already running the
  frontend build.** CodeBuild is a software build service; this pipeline is scientific data
  processing — a different workload shape (long-running, resource-heavier, data-dependent rather
  than code-dependent) that may or may not fit the same tool well. Reusing it would be convenient,
  not necessarily correct, and the compute-runner choice (CodeBuild vs. ECS vs. Batch vs.
  something else) is left open rather than defaulted to what's already there.

---

## Consequences

**Accepted:**

- A pipeline stage (DVC) and a storage format decision (still open) sit between raw ISIMIP/GGCMI
  data and anything the rest of the system can use — nothing downstream can consume raw NetCDF
  directly.
- Regional aggregation logic has to be correct and fast enough to run at query time, every time —
  there's no precomputed fallback if it's slow for an unusually large or oddly-shaped region.

**Gained:**

- Query-time cost is bounded by regional aggregation only, never by indicator count or warming-
  level count — exactly the property ADR-004 established for map data, now true for every
  scientific value the system produces, including the yield projection ADR-007 holds out.
- Counterfactual scope stays explicitly undecided rather than silently baked into the pipeline's
  shape, keeping that a real, deliberate future decision instead of an accidental one.

---

## Rejected options, summary

| Option | Reason |
|---|---|
| Compute baseline/driver/yield changes per query | Redundant against a bounded, precomputable option space — the same argument ADR-004 already made for map data |
| Precompute regional aggregation too | Region vocabulary is effectively unbounded; can't precompute for an unbounded space without restricting free-text queries |
| Build counterfactual support into the pipeline now | Premature — needs its own scientific scope decision first, not an engineering default |
| Airflow to orchestrate this pipeline | No recurring, multi-system complexity yet that DVC's own dependency tracking doesn't already handle |
| Kubeflow | No training loop exists yet; this pipeline is deterministic precompute, not model training |
| Continuous polling for new ISIMIP/GGCMI data | ISIMIP updates on long timescales, not daily; solving for a rate of change this data doesn't have |

---

## Revisit triggers

- **The access pattern is tested against a real storage format candidate** (Zarr or otherwise) —
  resolves the one deliberately open item in this ADR.
- **Counterfactual questions clear scientific scope review** — this ADR's pipeline shape may need
  to expand to support them; that expansion should be designed against the actual approved scope,
  not guessed at now.
- **The pipeline grows enough recurring, cross-system scheduling complexity** that DVC alone
  stops being sufficient — reopens Step 5's Airflow rejection.
- **A real training loop enters the system** — reopens Step 6's Kubeflow rejection, informed by
  whatever the actual training/fine-tuning need turns out to be (see ADR-007's evaluation-data
  capture, which is what would eventually feed such a loop). The concrete future shape most
  likely to justify it: the system expanding from agriculture into other ISIMIP sectors
  (fisheries, biome, etc.), each needing its own specialist model with its own recurring
  training/evaluation/promotion pipeline behind a routing layer — multiple recurring pipelines
  is the actual trigger, not "one model, occasionally fine-tuned."
- **Update cadence changes** — if GGCMI or ISIMIP releases start arriving frequently enough that
  manual trigger-tracking (Step 7) becomes a bottleneck, revisit whether a lightweight scheduled
  check is worth adding — still short of the daily-polling architecture this ADR rejects outright.
