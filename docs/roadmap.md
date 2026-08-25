# Roadmap

What's left after the offline scientific data pipeline (ADR-006), ordered by real dependency —
each phase is blocked on the one before it, except Phase 5, which runs alongside any of them.

This exists so implementation can move through a phase without re-deciding its open sub-questions
one at a time. Each phase lists the defaults I'll build against **unless you redirect** — silence
on a listed default means proceed with it, not that it's been re-opened for discussion. Starting
a phase still requires your explicit go-ahead; the defaults just remove the need to stop and ask
about each sub-decision once you've said "build it" for that phase.

---

## Phase 1 — Query-time regional lookup

**Scope:** the deterministic function that takes (region, crop, warming level or year, indicator)
and returns a value by reading directly from `process_global`'s precomputed store. No LLM
involved — this is the piece ADR-006 always described as "cheap regional aggregation over a
precomputed grid," now that the grid actually exists.

**Builds on:** this run's real `processed/global/` output, `gwl_year_table.json` (already built —
`timecode()` needs zero new work once this phase starts).

**Defaults:**
- Region resolution: bbox filter, then geometry filter, against the grid — already the pattern
  ADR-005 specifies, not a new decision.
- Region source of truth: promote the 5 demo regions out of `frontend/src/api/mockClient.ts`
  (`KNOWN_REGIONS`) into one shared definition both this lookup and the frontend read, instead of
  two copies that can drift.
- Compute topology: Lambda — now a locked decision (ADR-005), not just a Phase 1 default. The
  orchestration tier has no persistent state to amortize the way `understanding()` (Phase 2) and
  narration (Phase 3) do, which is why those two get ECS/Fargate and this doesn't.

---

## Phase 2 — Understanding Agent tool-calling

**Scope:** `geocode()`, `crop()`, `timecode()`, and the LLM-driven orchestration that calls them
(ADR-005).

**Builds on:** Phase 1 (the tools' output feeds Phase 1's lookup), `gwl_year_table.json`.

**Defaults:**
- `geocode()`: a fixed lookup over the same small region set Phase 1 already centralized — same
  shape as `timecode()` — not Amazon Location Service yet. The region vocabulary is small and
  bounded right now; reach for a real geocoding service only once it needs to be open-ended.
- `understanding()` hosting: FastAPI behind a single EC2 or Fargate task to start, per ADR-005's
  own "no Triton/vLLM ahead of a demonstrated need" reasoning. Not SageMaker yet.

---

## Phase 3 — Narration + verification gate

**Scope:** retrieval against the IPCC corpus, the Bedrock narration call, and ADR-007's
verification gate confirming narration never touches or alters a scientific value.

**Builds on:** Phase 1 (facts to narrate), Phase 2 (the resolved query narration responds to).

**Defaults:**
- Service boundary: RAG, generation, and verification deploy as one capability, not split into
  separate services (ADR-007) — RAG's only consumer is narration, no second consumer yet to
  justify the extra network hop.

**Still genuinely open, no default proposed:** the specific vector store and Bedrock model choice
— neither blocks Phase 1 or 2, so worth deciding when this phase actually starts, not
pre-committed now.

---

## Phase 4 — Frontend rewire

**Scope:** replace `mockClient.ts` with real `interpret`/`narrate` calls (ADR-004's split);
retire `precomputedClient.ts`'s defunct 5-region shape; build actual map shading (raw values from
the precomputed grid, client-side color scale — MapLibre's `image` source, no server-side
reprojection needed).

**Builds on:** Phase 1 alone is enough for `interpret` (map rendering, no narration text) to work;
Phase 3 for the narration panel.

**No default proposed here** — the color scale/legend was already deliberately deferred to this
point.

---

## Phase 5 — Cross-cutting, not sequential

Pick up opportunistically once the relevant piece it depends on exists, not in a fixed order:

- Langfuse tracing (ADR-005) — once the agent (Phase 2) exists to trace.
- CI/CD for the new backend services, once Phase 1 produces a deployable service.
- Region vocabulary growth past the initial 5 demo regions — once Phase 1's centralized region
  source exists to grow.
