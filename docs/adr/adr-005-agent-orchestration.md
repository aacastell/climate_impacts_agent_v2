# ADR-005: Agent Orchestration

**Status:** Accepted
**Depends on:** ADR-004 (map data delivery)
**Informs:** ADR-006 (offline scientific data pipeline), ADR-007 (narration verification gate)
**Scope:** How the system interprets a natural-language question and resolves it to a
structured, deterministic query. Covers the *serving shape* of the agent's own tool-calling
model (`understanding()` — an independent inference service, see Accompanying decisions) but not
the main API's own compute topology (Lambda vs. containers), RAG/vector infrastructure, or which
Bedrock model is used — those remain open.

---

## Context

The repo root README states a governing principle: *"The language model never emits a number,
and never decides what the answer is. It determines what question was asked, and narrates facts
it did not author."* That principle was declared before this system had an API tier at all — it
says what the agent must not do, but not what it does, or how "determines what question was
asked" is actually implemented as software. This ADR gives it a concrete shape.

Two things force a real design here, not "call the LLM with the question and a prompt":

- Resolution is multi-step and each step can fail independently: a region name has to become a
  geocoded location, a crop name has to be validated against the four supported crops, and
  warming-level or time phrasing has to resolve to a specific ISIMIP window. A single opaque
  LLM call collapses all of that into one step with no seam to catch or type any individual
  failure.
- ADR-004 already committed to precomputed data keyed by (region, crop, warming level,
  indicator). Something has to turn free text into that exact key before any deterministic
  lookup can run at all — the agent's real job is producing that key, not producing an answer.

---

## Decision

**A constrained "Understanding Agent" interprets the query and orchestrates tool calls —
`geocode()`, `crop()`, `timecode()` — to resolve it to a structured (region, crop, warming
level) tuple, manages ambiguity recovery, and hands that structured query to the deterministic
scientific layer (ADR-006). It never computes or emits a scientific value itself.** State is
short-lived and external, not a persistent session — consistent with ADR-001's "no persistent
conversation state."

**The agent's output feeds two separate downstream paths, not one.** The resolved (region, crop,
warming level) tuple is what ADR-004's `interpret` call returns to the frontend — which then
fetches map tiles directly from precomputed static files, never back through the agent or any
API response body. Only the narration path (ADR-007) continues on through the agent's evidence
gathering and generation. Nothing about this ADR's tool-calling design changes ADR-004's decision
that map data never travels through a request/response payload — the agent produces the *key*
map tiles are fetched by, not the tile data itself.

---

## How we got there

### Step 1 — Why not one LLM call that "figures out" the whole question?

Rejected. This is exactly the shape the governing principle already rules out: a single opaque
call gives no point at which to verify a resolved region or crop is actually valid before
deterministic code runs against it, and no way to produce the typed, deterministic refusals the
README's conventions already require ("Refusals are typed and deterministic, never a model
judgement call"). Splitting resolution into discrete tool calls gives each step its own
well-defined failure mode.

### Step 2 — Tools, or a fixed parser?

The current frontend mock (`MockApiClient`) resolves questions with keyword matching — adequate
for a demo, not for the real system. "How bad will it get for corn near Des Moines by
mid-century" needs actual language understanding to resolve to (Iowa, maize, ~2°C-equivalent
warming level) in a way regex can't reliably do, and the crop vocabulary, region vocabulary, and
phrasing of warming levels will all keep growing. An LLM-driven agent calling narrow,
deterministic tools gets the flexibility natural-language resolution needs while keeping every
individual resolution step auditable, typed, and independently testable — the tools themselves
stay ordinary deterministic code, only the decision of *which* tool to call and *how* to recover
from ambiguity is the LLM's job.

### Step 3 — Where does the agent's authority end?

This is the load-bearing decision. The agent orchestrates and interprets; it never touches a
scientific value. Once (region, crop, warming level) is resolved, everything downstream — grid
retrieval, spatial masking, weighted statistics, the yield projection itself — is deterministic
Python (ADR-006), never the LLM. This isn't a style preference: ADR-007's entire verification-gate
design depends on it. Holding the yield projection out of narration only means something if the
projection was never something the narrator (or the agent driving it) could have touched or
influenced in the first place.

### Step 4 — What makes the recovery behavior genuinely agentic, rather than a scripted retry?

A fixed rule like "if confidence < 0.5, retry" isn't meaningfully agentic — it's a threshold
check wearing agentic language. What earns the term: the agent observes a specific tool result,
diagnoses *what kind* of ambiguity or failure it is, chooses a recovery strategy suited to that
diagnosis (ask the user to disambiguate vs. retry with additional context vs. degrade), and only
then acts. That's the same interpret-and-decide authority Step 3 already grants the agent over
resolution, applied to its own failures, not just to the original question.

---

## Accompanying decisions

- **Interactive workflow, including clarification** (e.g., "did you mean spring wheat or winter
  wheat?"), but state is short-lived and external — no persistent session store keyed to a user.
  Concretely: a request that needs clarification returns a `query_id` and the specific question,
  with its partial resolution state written to a short-lived store (Redis is a candidate, not
  committed — see Revisit triggers); the follow-up request carries `query_id` plus the user's
  answer, retrieves that state, and resumes. **The workflow is stateful; the compute layer stays
  stateless** — no server instance needs to be the one that handles both requests, which is the
  same shape ADR-004's `interpret`/`narrate` split already established for a different reason.
  This is the same "no persistent conversation state" property ADR-001 and ADR-004 established,
  extended to cover mid-resolution clarification turns, not just repeat questions.
- **`geocode()`, `crop()`, and `timecode()` are not equally simple.** `geocode()` has to handle
  genuine ambiguity — "Mekong" can resolve to more than one candidate region — which is exactly
  the kind of case Step 4's recovery behavior exists for. Its output isn't just a lat/lon: the
  useful shape for the scientific layer to consume is closer to `{name, centroid, bbox, geometry,
  selected grid cells}`, resolved via bbox filtering (cheap) then geometry filtering (precise)
  against the precomputed global grid — cheap specifically because it's arithmetic against a
  known, regular grid (ADR-006's grid layout), not a spatial-database query. Amazon Location
  Service is a candidate implementation behind this interface, not a commitment — the agent and
  the scientific layer only depend on `geocode()`'s output shape, never on which provider produces
  it, the same reference-not-implementation pattern this ADR already uses for the tool-calling
  model itself. `crop()` resolves synonyms, spelling variation, and regional naming (corn vs.
  maize). `timecode()` is still, mechanically, a lookup table — `table[gwl] -> timewindow` — an
  earlier draft of this ADR called it "small," which undersold it: ADR-006's process stage now
  computes GWL for 67 individual years, not 3-4 checkpoints, so the real table has 67 entries, not
  a handful. **Known gap, not yet closed:** the process stage writes a `gwl_c` value alongside
  every field-window it produces, but never emits this table as its own small, dedicated artifact
  — the mapping currently only exists duplicated across ~871 field-window manifest entries, not as
  the one compact object `timecode()` actually needs for a direct lookup. This was meant to be
  built alongside the precompute pipeline and was missed — an implementation oversight, not a
  deferred scope decision like the *future* mode below. `timecode()`'s *future* mode, for
  arbitrary perturbation questions ("how would an arbitrary increase in consecutive dry days
  affect rice yields") can't be served from a lookup table at all, since region × arbitrary
  magnitude is combinatorial. That mode is kept planned, not implemented — the same "planned, not
  built" scope discipline ADR-006 applies to counterfactual questions, and not a coincidence: this
  is the tool that would actually serve those questions once counterfactual scope is approved.
- **The agent's own model is a distinct, smaller model from the narration model.** Tool-calling
  and resolution don't need the same capability narration does (ADR-007) — narration needs
  enough capacity to synthesize climate evidence and retrieved literature into coherent text,
  which is why that path leans toward Bedrock specifically. Using one model for both would be
  either over-provisioning resolution or under-provisioning narration. The exact tool-calling
  model, like the exact Bedrock model, remains open. **This model is `understanding()`** — see
  the next bullet for its serving shape; naming it explicitly here so "the Understanding Agent"
  (this ADR's orchestrator) and "`understanding()`" (the model that orchestrator's tool-calling
  runs on) don't read as two competing concepts. The agent is the orchestration logic;
  `understanding()` is the model powering its interpretation step.
- **`understanding()` is planned as an independently deployable inference service, not folded
  into the API process — resolving part of this ADR's own "backend compute topology... remains
  open" scope note, though not all of it.** Not *which* model — that's still open, per the bullet
  above — but *how* it's served. Expected to be small and CPU-only, so the initial serving shape
  is a plain FastAPI process behind EC2, ECS/Fargate, or a SageMaker endpoint — candidates, not a
  commitment — deliberately without reaching for Triton or vLLM ahead of a demonstrated need for
  them, the same reasoning ADR-006 already applies to Airflow and Kubeflow. This earns a real
  service boundary rather than staying an in-process call because it has a genuinely different
  resource/scaling profile than the rest of the API (a model held in memory, CPU-bound inference,
  its own latency curve) and its own lifecycle (fine-tuning, versioning, retraining) independent
  of the API's own request-handling code — not "the project has an ML model, so it needs a
  service." This is also, as far as this project currently plans, the only place a `model.train()`
  step exists at all — worth being explicit about, since it's the concrete trigger ADR-006's
  Kubeflow revisit-trigger language now technically satisfies (see that ADR's updated note) even
  though the actual threshold for needing Kubeflow — multiple recurring pipelines, not one model
  — still isn't met.
- **Langfuse traces the full agent path** — query → agent decisions → tool calls → retrieval →
  generation → verification → retry — specifically so a failure is diagnosable ("why did the
  agent fail on this query") rather than an opaque outcome. Hosting is managed/cloud, already
  settled in this project's own discussion — no new AWS infrastructure follows from this.

---

## Consequences

**Accepted:**

- An extra hop compared to a single LLM call — question → agent → tool calls → structured query
  — with more intermediate state to reason about. This is exactly why Langfuse traces the path;
  the complexity is real, and it needs to be observable, not hidden.
- The agent's tool vocabulary (`geocode`, `crop`, `timecode`) is a new interface surface that
  has to be designed, versioned, and kept in sync with what the scientific layer and precomputed
  data actually support.
- Clarification turns depend on a short-lived state store existing at all — a new piece of
  infrastructure with its own availability and expiry behavior to get right, even though it's
  deliberately kept out of the compute layer's own state.

**Gained:**

- Every resolution step can fail on its own terms with a specific, typed refusal, rather than
  the whole question either fully succeeding or failing opaquely.
- The scientific layer (ADR-006) never receives free text — only a validated structured query —
  so its own correctness is a data-pipeline problem, not a language-understanding problem, per
  the README's original two-grounding-paths framing.

---

## Rejected options, summary

| Option | Reason |
|---|---|
| Single LLM call resolving the whole question | No seam for typed refusals or per-step validation before deterministic code runs |
| Fixed rule-based parser (keyword/regex) for the real system | Doesn't generalize past the current mock's demo phrasing; kept only as the disposable mock, not the production design |
| Agent computes or adjusts scientific values directly | Violates the governing principle and breaks the precondition ADR-007's verification gate depends on |

---

## Revisit triggers

- **The tool vocabulary stops being sufficient** (a new resolution dimension is needed beyond
  region/crop/warming-level) — extend Step 3's tool set rather than expanding what any one tool
  is responsible for.
- **The short-lived state store needs an actual implementation choice.** Redis is a candidate,
  not a requirement — pick it (or an alternative) once real request volume and clarification
  frequency exist to size it against.
- **A NASA infrastructure team's own agent/orchestration standard takes ownership** — same class
  of trigger ADR-001 and ADR-003 already carry for their respective layers.
