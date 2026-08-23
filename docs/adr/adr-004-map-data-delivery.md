# ADR-004: Map Data Delivery

**Status:** Accepted
**Depends on:** ADR-001 (static delivery via S3 + CloudFront)
**Scope:** How map shading data (climate indicators, sector/crop outputs) reaches the frontend,
and how that interacts with the query API. Does not cover the API tier's own architecture,
compute, or language — that remains open (see repo root README "Status" table).

---

## Context

The frontend is growing a requirement ADR-001 didn't need to address: the climate map must let
a user toggle between several indicators (temperature change, precipitation change, consecutive
dry-day change, and others as the scientific scope expands) without a page reload or a visible
wait. The data behind each indicator is a full grid — in the worst case, global coverage at
ISIMIP's native resolution, for every indicator, every warming level, every crop model where
applicable. That is a large option space, even though any single question only ever needs a
thin slice of it.

Two questions this ADR answers:

1. Where does that grid data live, and how does it get to the map?
2. Does splitting "the map is ready" from "the narration is ready" — so the map can render
   before the LLM-generated narration finishes — threaten the "no persistent conversation
   state" requirement ADR-001 already established?

---

## Decision

**Precompute the full indicator option space once, offline, and serve it as static tiles from
a dedicated bucket added as a second origin on the existing CloudFront distribution — never as
part of the query API's response body.** The query API is split into two calls: a fast,
stateless **interpret** call that resolves the question to a region/crop/warming-level/indicator
selection, and a slower, independently stateless **narrate** call that takes that resolved
interpretation as its own input.

---

## How we got there

### Step 1 — Does shading data belong in the query response at all?

The instinct to compute or extract shading data per request was rejected before it was built.
The set of (indicator × warming level × crop model) combinations is bounded and known in
advance — nothing about it depends on which question a user happens to ask. Recomputing or
re-extracting a slice of it per request is redundant work against a fixed, precomputable option
space, and it means every query response carries a payload sized to the shading data rather
than to the question — the two are unrelated to each other, and the latter is always small
(interpretation, narration text, provenance, disclaimers).

**→ Precompute the full option space offline, once**, as an artifact of the same deterministic
Python data pipeline the repo README already assigns computed facts to. The query API never
computes or extracts shading values; it only tells the frontend which precomputed slice to load.

### Step 2 — Does a tile pyramid actually bound the transfer cost, given regions range from a
town to a subcontinent?

Yes, and not by an explicit size cap. A tile pyramid bounds transfer by **screen area and zoom
level**, not by the real-world extent of the region being viewed: a fixed number of tiles fills
the viewport at whatever zoom the map is at, whether that viewport is showing a town in Iowa or
all of Europe. Zooming out to see a larger area doesn't fetch more data — it fetches the same
few tiles from a coarser zoom level. An explicit region-size cap would be solving a problem the
tiling scheme doesn't have.

What *does* bound the design is the precompute side, not the query side: there is no reason to
tile past ISIMIP's native resolution (~0.5°) — finer zoom levels than that would be interpolating
detail the source data doesn't contain. That ceiling, plus the number of indicators and warming
levels, sets a one-time storage and precompute cost. It does not scale with traffic or with how
any individual question happens to resolve.

**→ No region-size cap.** The zoom ceiling is set by data resolution, not by policy.

### Step 3 — Which bucket, and how does it reach the frontend?

**Same bucket as the frontend build — rejected.** `scripts/upload-frontend.sh` runs
`aws s3 sync --delete` against the frontend bucket on every deploy. Tile data sharing that
bucket would be one un-scoped sync away from deletion by an unrelated frontend release, and it
would mix two artifacts with entirely different deploy cadences and owners under one pipeline —
exactly the mistake ADR-003 already named and avoided for `infra/` vs. `frontend/`, for the same
underlying reason: the data pipeline changes rarely and deliberately; the frontend deploys on
every push.

**→ A separate bucket**, populated by the data pipeline's own process, added as a second origin
on the *existing* CloudFront distribution via a path pattern (e.g. `/tiles/*`). This is precisely
the case ADR-001 built room for: *"Single-distribution multi-origin routing remains
available... Full control of cache behaviours, which matters if map tiles are later served
through the same distribution."* One domain, no CORS, same WAF and security headers, separate
ownership and lifecycle.

**Tile format** is left to implementation, not fixed by this ADR — a single static archive
format servable via HTTP range requests directly from S3/CloudFront (no tile server process) is
the requirement; anything meeting that bar is consistent with this decision.

### Step 4 — Splitting interpret from narrate: does this reopen "no persistent conversation
state"?

No — but only if it's built correctly, so the constraint is worth stating precisely.
"No persistent conversation state" (ADR-001) means the server retains no memory tied to a user
*across separate questions*. It does not mean a single question must resolve in exactly one
HTTP round trip. REST statelessness requires that each request carry everything the server needs
to handle it — not that there be only one request.

The failure mode to avoid: a `narrate` call that says "continue job `abc123`," requiring the
server to remember what call 1 did. **The `narrate` call must take the resolved interpretation
itself as input** (region, crop, warming level, indicator — not an opaque job ID), making it a
pure function: same interpretation in, same narration out, servable by any backend instance with
no shared memory between the two calls. Built this way, splitting the calls doesn't just avoid
breaking statelessness — it's a stronger stateless property than one bundled call would default
to, since narration becomes independently retryable and independently cacheable.

**→ Two calls, both self-contained.** `interpret` resolves fast (deterministic region/crop/
warming-level parsing, no retrieval); the frontend can fly the map to the right bounding box and
load tiles for both maps immediately. `narrate` (retrieval against the IPCC corpus, LLM
generation, and whatever verification gate the API tier ends up requiring) fills in the text
panel when it's ready, on its own clock.

---

## Consequences

**Accepted:**

- A new bucket and CloudFront origin to provision and own, separate from the frontend bucket —
  more moving parts than a single-bucket design, in exchange for deploy-safety and cadence
  separation.
- The `narrate` call's statelessness is a constraint on the API tier's future design, not just a
  suggestion: it must be implementable as a pure function of the interpretation. This shapes
  API-tier work that hasn't started yet.
- Tile format and precompute pipeline details are left open, deliberately — inventing them here,
  ahead of the data pipeline's own design, would misrepresent them as settled.

**Gained:**

- Query API responses stay small and fast regardless of how many indicators exist or how large a
  resolved region is — indicator count and region size never enter the per-request cost.
- Both maps can render before narration exists, since map data no longer depends on LLM
  generation or retrieval completing first.
- This resolves the "precompute vs. on-demand" open item (repo README "Status" table) for map
  shading data specifically: precompute, always. It remains open for narration, which is a
  separate, still-undecided question.

---

## Rejected options, summary

| Option | Reason |
|---|---|
| Compute/extract shading data per query | Redundant against a bounded, precomputable option space; ties response size to data size instead of question size |
| Shading data in the same bucket as the frontend build | `--delete` sync on every frontend deploy risks deleting it; mixes two artifacts with different owners and deploy cadences |
| Explicit region-size cap on queries | Solves a transfer-cost problem tiling already solves by zoom level; the real ceiling is data resolution, not policy |
| `narrate` call referencing a server-side job ID | Reintroduces the persistent state ADR-001 ruled out, for no benefit over passing the interpretation directly |

---

## Revisit triggers

- **A tile format or precompute tool proves unworkable** at the actual data volumes once the
  pipeline is built — revisit Step 3's format choice specifically; the bucket/origin/statelessness
  decisions don't depend on which format is chosen.
- **The API tier's own architecture** (once designed) can't cleanly support two independent,
  stateless calls — revisit Step 4. This should be a rare trigger; most backend architectures
  support this pattern without difficulty.
- **Indicator count or resolution grows enough that the one-time precompute/storage cost becomes
  the binding constraint** rather than a fixed cost — revisit the zoom ceiling in Step 2.
