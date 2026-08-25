# ISIMIP Climate Explorer — v2

A public web interface for exploring how projected climate change affects agriculture, using
ISIMIP sector projections grounded in IPCC-assessed literature.

A user asks a question about a region, crop, and global warming level. The system returns two
maps — climate and sector projections — and a narration that explains them.

> **v2 is a greenfield rebuild.** It shares goals with the earlier prototype but no code,
> and no design decision carries over implicitly.

---

## Governing principle

**The language model never emits a number, and never decides what the answer is.** It
determines what question was asked, and narrates facts it did not author.

There are two independent grounding paths, and they are kept separate:

| Path | Source | Correctness is a… |
|---|---|---|
| Computed facts | ISIMIP outputs, deterministic Python | data-pipeline problem |
| Retrieved framing | IPCC corpus | citation problem |

They are reconciled explicitly, never implicitly inside a model.

How this is actually implemented — the agent that resolves a question without touching scientific
values ([ADR-005](docs/adr/adr-005-agent-orchestration.md)), the pipeline that supplies the facts
it narrates ([ADR-006](docs/adr/adr-006-offline-scientific-data-pipeline.md)), and how narration
is checked against a held-out projection before anything is published
([ADR-007](docs/adr/adr-007-narration-verification-gate.md)).

---

## Scope

| | |
|---|---|
| Sector | Agriculture, non-irrigated (`noirr`) |
| Crops | Maize, spring wheat, soy, rice |
| Climate model | GFDL-ESM4 |
| Scenario | SSP3-7.0 |
| Crop models | LPJmL only (MVP — see note below) |
| Run specifiers | `2015soc` (no adaptation); both CO₂ specifications, reported as a range |
| Corpus | IPCC reports |

**MVP note, not a permanent scope decision:** pDSSAT is dropped entirely for now. Verified
directly against ISIMIP's catalog — pDSSAT has no SSP3-7.0 output at all for GFDL-ESM4 (only
`historical`, `ssp126`, `ssp585`), so the pDSSAT/LPJmL combination this scope table used to name
cannot produce a future projection under this system's own climate model and scenario. Baseline
validation still has both models available; only the future/warming-level yield projection is
affected. Accepted consequence, not discovered later: **there is currently no second crop model
to range against for yield projections** — revisit after MVP.

**Two facts that must appear in every answer**, because they are easy to misread as forecasts:

- `2015soc` means management is frozen at 2015 conditions — **no adaptation is represented**.
- A single climate model provides **no climate-model uncertainty range**. Normally two crop
  models would give a range, not a distribution — but see the MVP note above: right now there is
  only one crop model, so the yield figure is a single-model estimate, not a range either.

**Target scale:** roughly 1,000 users. Roughly 2–10 seconds latency for a normal request; roughly
30 seconds is acceptable for a cache miss or other exceptional case. This is the number that
[ADR-006](docs/adr/adr-006-offline-scientific-data-pipeline.md)'s precompute decision is actually
sized against — the online path only has to do cheap regional aggregation over a precomputed
grid, never the expensive temporal processing, which is what makes this target plausible at all.

---

## Status

| Area | State |
|---|---|
| Frontend delivery | Decided — [ADR-001](docs/adr/adr-001-frontend-hosting.md) |
| Frontend framework | Decided — [ADR-002](docs/adr/adr-002-frontend-framework.md) |
| Infrastructure provisioning | Decided — [ADR-003](docs/adr/adr-003-infrastructure-provisioning.md) |
| Map data delivery | Decided — [ADR-004](docs/adr/adr-004-map-data-delivery.md) |
| Agent orchestration | Decided — [ADR-005](docs/adr/adr-005-agent-orchestration.md) |
| Offline scientific data pipeline | Decided — [ADR-006](docs/adr/adr-006-offline-scientific-data-pipeline.md); compute runner still open |
| Verification gate | Decided — [ADR-007](docs/adr/adr-007-narration-verification-gate.md) |
| Vector database for RAG | Decided (deferred, with trigger) — [ADR-008](docs/adr/adr-008-vector-database-for-rag.md) |
| Orchestration framework choice | Decided — [ADR-009](docs/adr/adr-009-orchestration-framework-choice.md): LangGraph for narration()'s retry loop, plain loop for understanding() |
| API tier | Decided — [ADR-005](docs/adr/adr-005-agent-orchestration.md): Lambda for orchestration, ECS/Fargate for `understanding()`/narration |
| Precompute vs. on-demand | Decided — precompute globally for scientific calculations (ADR-004, ADR-006); regional aggregation and narration generation itself happen at query time |
| Indicator set and aggregation rules | Open — pending scientific sign-off |

---

## Stack (decided so far)

**Frontend** — React, TypeScript, Vite, MapLibre GL JS. Built to static files, served from S3
behind CloudFront (self-assembled, not Amplify). CloudFront Functions handle SPA fallback
routing and security headers; WAF attaches at CloudFront for the public traffic ceiling.

Standing constraints from ADR-002:

- Keep the dependency tree deliberately small — this is a public, security-scanned site.
- Pin the React major version; upgrade on our schedule, not because a transitive dependency
  forced it.

---

## Decision records

Architecture decisions live in `docs/adr/`. Every ADR states what was chosen, what was
rejected and why, and — importantly — its **revisit triggers**, so a future reader can tell
when a decision has stopped being valid rather than discovering it the hard way.

The trigger most likely to fire: **if answer URLs must become shareable and indexable**, the
static-delivery decision reopens.

What's left to build, in dependency order, is tracked in [`docs/roadmap.md`](docs/roadmap.md) —
separate from this table, which tracks *decided vs. open*, not *build order*.

---

## Conventions

- No prices, quotas, or service limits in documentation. They go stale invisibly. Record the
  *shape* of a cost and verify current figures against vendor docs when needed.
- Every published answer carries a provenance record: data version, indicator version, model
  identifier, prompt version.
- Refusals are typed and deterministic, never a model judgement. A high refusal rate is an
  accepted design property, not a defect.

---

## Repository layout

```
docs/adr/     architecture decision records
frontend/     React + TypeScript application
infra/        AWS CDK app (Python) provisioning the system's cloud resources
```

Further directories are added as those areas are designed.
