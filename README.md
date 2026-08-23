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

---

## Scope

| | |
|---|---|
| Sector | Agriculture, non-irrigated (`noirr`) |
| Crops | Maize, spring wheat, soy, rice |
| Climate model | GFDL-ESM4 |
| Scenario | SSP3-7.0 |
| Crop models | pDSSAT, LPJmL |
| Run specifiers | `2015soc` (no adaptation); both CO₂ specifications, reported as a range |
| Corpus | IPCC reports |

**Two facts that must appear in every answer**, because they are easy to misread as forecasts:

- `2015soc` means management is frozen at 2015 conditions — **no adaptation is represented**.
- A single climate model provides **no climate-model uncertainty range**. Two crop models give
  a range, not a distribution: report the range, never a mean or confidence interval.

---

## Status

| Area | State |
|---|---|
| Frontend delivery | Decided — [ADR-001](docs/adr/adr-001-frontend-hosting.md) |
| Frontend framework | Decided — [ADR-002](docs/adr/adr-002-frontend-framework.md) |
| Infrastructure provisioning | Decided — [ADR-003](docs/adr/adr-003-infrastructure-provisioning.md) |
| Map data delivery | Decided — [ADR-004](docs/adr/adr-004-map-data-delivery.md) |
| API tier | Open |
| Precompute vs. on-demand | Decided for map data (precompute — ADR-004); open for narration |
| Indicator set and aggregation rules | Open — pending scientific sign-off |
| Verification gate | Open |

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
