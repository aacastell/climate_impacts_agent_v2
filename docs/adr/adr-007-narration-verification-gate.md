# ADR-007: Narration Verification Gate

**Status:** Accepted
**Depends on:** ADR-005 (agent orchestration), ADR-006 (offline scientific data pipeline —
supplies the held-out yield projection)
**Scope:** How generated narration is checked against the scientific projection it's supposed to
explain, and what happens when it doesn't match. Does not cover which Bedrock model is used, the
specific vector database/embedding technology, or the eventual continuous-training (CT) pipeline
design. RAG's *service boundary* — bundled with narration, not split into a separate service — is
resolved; see Accompanying decisions.

---

## Context

The repo root README's governing principle says the LLM narrates facts it did not author. That
prevents the model from inventing a number, but it doesn't prevent a different failure: narration
is still generated text describing a scientific result, and nothing in "don't emit a number"
stops that text from getting the *direction* or *magnitude* wrong, describing an unsupported
mechanism, or flatly contradicting the projection it's meant to explain. A plausible-sounding
wrong explanation is a worse outcome than a typed refusal (README convention: refusals are typed
and deterministic; "a high refusal rate is an accepted design property, not a defect") — it's
wrong in a way that isn't visibly wrong.

---

## Decision

**Split evidence into two epistemically distinct sets.** Narration is generated from climate and
crop evidence, region, and retrieved scientific literature — never from the yield projection
itself, which is held out. The yield projection is used afterward to verify the narration through
a structured consistency judgment (direction, severity alignment, unsupported claims,
contradictions, confidence) — not a freeform "does this sound right." On failure, a bounded
retry/recovery policy runs; if still unresolved after N attempts, the system publishes a
qualified response and terminates in a distinct `SCIENTIFIC_DISAGREEMENT` state, not
`AGENT_FAILURE`. Every such case is captured as structured evaluation data.

---

## How we got there

### Step 1 — Why hold the yield projection out of narration generation at all?

If narration generation could see the actual yield number, verification against that same number
would be circular — the model could simply restate a number it already had, and a "consistency
check" would prove nothing about whether its explanation is actually grounded in the evidence it
was given. Holding the projection out turns verification into a real test: does an explanation
built from climate evidence, crop context, and literature — generated blind to the outcome —
agree with an independently computed outcome it never saw? That's an actual consistency check,
not confirmation of something the model already knew.

### Step 2 — Why a structured judgment instead of a freeform "does this sound right" check?

A freeform LLM-judges-LLM pass/fail is opaque and gives the recovery policy nothing to act on —
having learned only "no," what would a retry even revise? A structured judgment (direction,
severity alignment, unsupported claims, contradictions, confidence) gives the recovery policy a
specific target (a directional contradiction calls for a different fix than an unsupported
mechanism claim) and gives the eventual evaluation dataset a labeled shape from the start, rather
than needing to be manually labeled later.

### Step 3 — What does the recovery policy do, and why is it bounded?

`PASS` publishes. `FAIL` triggers revision — regenerate narration, or retrieve additional
literature — up to N attempts. Unbounded retry is rejected outright: real cases exist (Step 4)
where no amount of revision converges, because the disagreement isn't a narration-quality
problem. An agent that retries forever against a case it structurally cannot resolve is a
liveness problem, not a quality one, and would silently hang the response the user is waiting on.

### Step 4 — Why `SCIENTIFIC_DISAGREEMENT`, not `AGENT_FAILURE`, when retries are exhausted?

This is the sharpest point in the design. A narration that still fails to reconcile with the
yield projection after N genuine attempts has two possible explanations: the narrator is failing
at the task, or the literature-grounded explanation and the crop model's projection actually
disagree with each other — for example, climate evidence and literature both point toward yield
decline, while the underlying crop model (GGCMI) projects a yield increase. That second case is
not a bug; it's a legitimate, interesting scientific finding — literature and model response
diverging is exactly the kind of thing worth surfacing, not hiding. Forcing the LLM to keep
revising until it manufactures agreement with the model would be scientifically dishonest: it
would produce the appearance of consistency where none actually exists. Terminating in a
distinct, typed state instead is the same principle the README already applies to input
refusals ("typed and deterministic, never a model judgement call"), extended to output
verification — a disagreement is reported as what it is, not silently resolved by brute-force
retrying.

### Step 5 — What happens to unresolved cases?

Every `SCIENTIFIC_DISAGREEMENT` (and more broadly every case that doesn't cleanly `PASS`) is
captured as structured evaluation data: query, climate evidence, literature evidence, model
yield projection, generated narration, verification result, and resolution. This is what gives
the "eventual CT/model-quality loop" — explicitly deferred rather than built speculatively in
ADR-006's rejection of Kubeflow — an actual reason to exist later: a real, accumulating,
labeled dataset of exactly the cases worth learning from, rather than infrastructure introduced
ahead of any evidence it's needed.

---

## Accompanying decisions

- **MLflow tracks the evaluation loop this gate produces specifically** — model version →
  evaluation dataset → tool-calling accuracy → consistency accuracy → model candidate — not a
  generic "ML systems have MLflow" justification. Hosting is managed/cloud, already settled.
  SageMaker was considered for the training/hosting side of this same lifecycle and not selected
  — worth re-evaluating once there's an actual model to train or host, not before.
- **RAG retrieves literature explaining mechanisms, never numerical results.** Its job is
  supplying evidence like heat stress / water stress / crop reproductive sensitivity — the
  causal or mechanistic framing narration draws on — not ISIMIP/GGCMI values, which come
  exclusively from ADR-006's pipeline. If RAG could return a number, it would reopen exactly the
  hole this ADR closes: an unverified numeric claim entering narration from a second, uncontrolled
  path.
- **RAG, generation, and verification are one deployable capability, not split into separate
  services.** RAG's only current consumer is narration — splitting it out now would add a network
  hop with no second consumer to justify it, the same "no boundary without demonstrated need"
  reasoning this project already applies to Airflow (ADR-006) and to keeping `crop()`/`timecode()`
  as local tools rather than services (ADR-005). Revisit if RAG ever needs to serve a consumer
  beyond narration. This resolves the service-boundary half of this ADR's "RAG/vector
  infrastructure... remain[s] open" scope note — the specific vector database/embedding technology
  is still open; only the deployment topology is settled.
- **Bedrock is the candidate for narration specifically because it needs more capability than the
  agent's own tool-calling model** (ADR-005) — synthesizing climate evidence and retrieved
  literature into coherent, accurate text is a harder generation task than resolving a region or
  crop. The exact Bedrock model remains open.
- **The verifier does not adjudicate which of literature or crop model is "right" when they
  disagree.** That's a scientific judgment call, and it belongs with the same "pending scientific
  sign-off" process the README already reserves for indicator set and aggregation rules — not
  something engineering decides inside a verification check.

---

## Consequences

**Accepted:**

- A published answer can now carry a "qualified — scientific disagreement flagged" status, even
  after retries succeed at nothing. That's a new response state the frontend has to communicate
  clearly, distinct from both a clean answer and a typed refusal — UI/UX design work that doesn't
  exist yet.
- The retry bound N is a new tuning parameter with no principled starting value yet — it has to
  be set from production behavior, not guessed in the abstract.

**Gained:**

- The narrator can be evaluated without trusting it: narration quality becomes measurable against
  an independently-held-out ground truth, rather than requiring human review of every case to
  catch a bad explanation.
- Difficult production cases become the evaluation set automatically, rather than needing to be
  manufactured or hand-curated separately.
- A model–literature disagreement is preserved as a finding instead of being erased by forced
  retry convergence — scientifically more honest, and more useful to whoever eventually reviews
  these cases.

---

## Update (2026-08-26): two deterministic checks added ahead of verify

Real, disclosed gap this closes, not new scope invented for its own sake: the original verify
step was an LLM judging direction/severity/unsupported-claims against the held-out yield number —
real, but it left two things unchecked. (1) Nothing verified that a specific number appearing in
generated narration text actually traced back to something generation was given — a fabricated
figure that happened to be direction-consistent would still `PASS`. (2) Nothing gave the verifier
a signal to check a narrated *mechanism* claim against — a narration citing the wrong driver
(heat stress when the region's actual pattern tracks water stress) could be numerically correct,
directionally correct, and still wrong in a way that matters for a mitigation recommendation.

**Two new deterministic nodes now run between generate and verify** (`services/narration/graph.py`):

- **`guard_numbers`** (`services/narration/number_guard.py`) — regex-extracts every numeric token
  from the narration, checks each against the numbers generation was actually given (climate
  evidence, retrieved literature, the warming level itself). Any number with no real source
  triggers the same bounded retry as a verify `FAIL` — no LLM call spent confirming what a
  deterministic check already caught.
- **`covariation_check`** (`pipeline/climate_pipeline/process/covariation.py`) — for the queried
  region, computes the Spearman correlation between each climate driver's per-cell grid and the
  crop yield's per-cell grid (both already stored by the process stage as full grids, not
  scalars — see `process/run.py`'s `_write_field_window`). This is a real, computable
  co-variation signal, not causal proof, and is explicitly not trusted below
  `MIN_CELLS_FOR_CONFIDENCE` region cells (the same small-n caution
  `services/understanding/finetune/drift_stats.py`'s own statistical test already discloses). The top confident driver is given to the verifier, which
  judges `mechanism_consistent` — matching a driver name to a narration's free-text mechanism
  claim is a semantic call, not something a correlation coefficient decides on its own.

**Still open, matching this ADR's original "verifier does not adjudicate" stance:** this signal
narrows the mechanistic-attribution gap named in `review/mechanistic-attribution-boundary.md`; it
does not close it. True causal (not just statistical) attribution — the longer-term path also
named there — remains a separate, undone piece of work.

**Tracking:** both checks are Langfuse-traced (`@observe(as_type="tool")`, matching how
`orchestrator.py` already tags deterministic tool calls) for per-call diagnosis, and logged as
their own MLflow params/metrics via `eval_capture.py` for aggregate reporting —
`services/narration/report_verification_rates.py` is the real aggregation script this ADR's own
Step 5 named as a gap: per-dimension pass rates (number provenance, mechanism consistency where
judged, direction/severity), not one blended number.

---

## Rejected options, summary

| Option | Reason |
|---|---|
| Generate narration with the yield projection visible | Makes verification circular — the model could just restate what it was already shown |
| Freeform "does this sound right" LLM-judge check | Opaque pass/fail gives the recovery policy nothing specific to act on |
| Unbounded retry until consistent | Some disagreements can't converge because they're real, not a narration defect — infinite retry would hang on exactly those cases |
| Treat every unresolved case as agent failure | Erases the possibility of a genuine literature/model disagreement, which is scientifically dishonest to force-resolve |

---

## Revisit triggers

- **The `SCIENTIFIC_DISAGREEMENT` rate in production is high enough** to suggest a systematic
  issue (e.g., a specific crop/region combination consistently disagreeing) rather than isolated
  cases — worth a scientific review pass, not an engineering fix.
- **The retry bound N needs real tuning** once production data exists to tune it against.
- **A real CT/fine-tuning pipeline gets built**, informed by the accumulated evaluation dataset —
  reopens ADR-006's deferred Kubeflow decision with actual evidence behind it instead of none.
