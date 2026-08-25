# ADR-009: Orchestration Framework Choice — LangGraph for narration(), Not for understanding()

**Status:** Accepted
**Depends on:** ADR-005 (agent orchestration — defines `understanding()`'s tool-calling loop),
ADR-007 (narration verification gate — defines the generate/verify/retry semantics this ADR now
implements as a graph)
**Scope:** Whether `understanding()` and/or `narration()`'s control flow should be built on an
orchestration framework (LangGraph) rather than a plain Python loop, and if so, where. Does not
reopen ADR-005's or ADR-007's own resolved decisions about what those control flows *do* — only
how they're implemented.

---

## Context

This project's own predecessor (v1, `climate_impacts_agent`) used LangGraph for its entire
pipeline — one compiled `StateGraph` spanning resolution, retrieval, narration, and verification
as a single object, coordinating two independent bounded-retry loops through a shared ~15-field
state (`AgentState`, with `Annotated[list, operator.add]` reducers accumulating tool calls and
assumptions across nodes). That system's "understanding" step was a single-shot extraction via an
already-trained fine-tuned router model, followed by deterministic, hardcoded tool calls — the
retry lived in the *graph*, not in a model iteratively reasoning about what to do next.

This project (v2) built `understanding()` as a real, model-driven tool-calling loop (ADR-005) —
the model itself decides which of five tools to call, in what order, and when it's resolved —
implemented as a plain bounded loop, no framework. `narration()`'s generate/verify/retry flow
(ADR-007) was likewise a plain loop. Neither used LangGraph. That absence was reasoned through
directly, not left implicit: v2 split what v1 ran as one coordinated process into two separately
deployable services (ADR-005, ADR-007's service-boundary resolution), and each resulting piece's
control flow is simple enough — one conditional in `understanding()`'s case — that a graph
abstraction had nothing real to coordinate.

That reasoning holds architecturally. It doesn't settle the actual question, which turned out to
be broader: demonstrated need isn't only about internal system complexity. It can also mean an
external, real requirement — in this case, LangGraph experience being specifically valued for the
role this project is portfolio evidence for. That's a legitimate reason to adopt a technology on
its own, separate from whether the code technically requires it — but it doesn't excuse using it
badly. The question this ADR actually resolves is *where* to use it so the choice is honest and
defensible under direct questioning, not just present.

---

## Decision

**Rebuild `narration()`'s generate/verify/retry loop as a real LangGraph graph. Leave
`understanding()`'s tool-calling loop as a plain loop.** This is not "use it everywhere for
consistency" or "use it nowhere to stay minimal" — it's a scoped, deliberately asymmetric choice,
made because the two loops are not actually the same shape.

---

## How we got there

### Step 1 — Why narration()'s loop is a genuine fit

`narration()`'s retry logic branches between three real, distinct outcomes — `PASS`, retry, and a
terminal `SCIENTIFIC_DISAGREEMENT` once retries are exhausted (ADR-007 Step 4) — coordinated
across two separate model calls (`generate`, `verify`) with deliberately different visibility
into the same held-out number. That's real branching between named functions, with genuine
multi-terminal-state routing. Generate→verify→self-correct loops are the standard, legitimate
LangGraph use case this pattern was built for — not a stretch to fit it in.

### Step 2 — Why understanding()'s loop is not the same fit

`understanding()`'s branching happens *inside a single Bedrock Converse call's own tool-selection
reasoning* — the model decides which tool to call next as part of one generation, not as a Python
function returning control to an orchestrator that then routes to another named node. There's
nothing for a graph to coordinate that the model isn't already coordinating itself. Wrapping this
loop in LangGraph would mean a graph with effectively one real node (call the model, run whatever
tool it picked, decide whether to loop) — a thin shell around the same loop, present in name only.
That's a materially weaker demonstration of the framework than a genuine multi-node fit, and it's
the kind of gap a direct question in review ("walk me through why this needed to be a graph")
would expose immediately.

### Step 3 — Why not skip LangGraph anywhere, per the original architectural reasoning

The original "no framework without demonstrated internal need" argument (same family as ADR-006's
Airflow/Kubeflow rejections and ADR-008's vector-DB deferral) is still correct on its own terms —
but it was answering the wrong question in isolation. It only accounts for internal
system-complexity need. A portfolio project's demonstrated need can legitimately include what the
audience evaluating it actually wants to see, provided that's stated plainly rather than
disguised as an architecture-driven decision it wasn't.

### Step 4 — Why this doesn't compromise the earlier design

`narrate()`'s public contract — function name, parameters, return shape (`narration`,
`verification`, `status`, `attempts`, `literature`) — is unchanged. `app.py` and every existing
test in `test_narrate.py` pass against the graph-backed implementation without modification,
confirmed directly, not assumed: the rewrite is a genuine drop-in replacement of the loop's
internals, not a parallel implementation that happens to agree with the old one on the tests
written so far.

---

## Accompanying decisions

- **State carries live Python objects (`model_client`), not serialized handles.** This graph is
  compiled and invoked in-process per request, never checkpointed or persisted across a process
  boundary — LangGraph's state doesn't need to be JSON-serializable here, and forcing it to be
  would be complexity with no real backing need, the same category of mistake this ADR is
  otherwise trying to avoid.
- **Retrieval stays outside the graph, run once before it's invoked.** `narrate.py` resolves
  literature once, then hands the graph a fixed literature list — matching ADR-007's original
  semantics (retrieval isn't retried per attempt) without needing a third graph node whose only
  job would be running once and never looping.
- **Tracing responsibility split, not duplicated.** The outer `narrate()` function keeps its
  existing chain-level Langfuse span; the underlying `generate()`/`verify()` model-client calls
  already carry their own per-call spans (`model_client.py`). The graph nodes themselves aren't
  separately wrapped — that would be redundant instrumentation layered over spans that already
  exist at the right granularity.
- **v1's router pattern (a real, already-trained fine-tuned extraction model) is directly
  relevant to this project's separate, still-open fine-tuning plan for `understanding()`** — noted
  here because it surfaced during this investigation, not resolved here; that's tracked
  separately, not part of this ADR's scope.

---

## Consequences

**Accepted:**

- The system now uses two different control-flow patterns for its two model services — a plain
  loop and a compiled graph — rather than one consistent pattern throughout. That asymmetry has
  to be explained, not hidden, whenever this system is walked through; this ADR is that
  explanation.
- LangGraph is now a real dependency of `narration()` specifically, not the whole system —
  `understanding()` has no LangGraph dependency at all.

**Gained:**

- A real, defensible LangGraph usage example exists where the fit is genuine, not manufactured —
  survives direct questioning about *why* it's a graph, because the honest answer is architectural,
  not just "the framework was available."
- The distinction itself (adopted here, not there, and here's precisely why) is stronger evidence
  of framework judgment than uniform adoption or uniform avoidance would have been — knowing where
  a tool fits is a different, more senior claim than knowing how to use the tool at all.

---

## Rejected options, summary

| Option | Reason |
|---|---|
| LangGraph for both understanding() and narration() | understanding()'s loop has no real multi-node branching to coordinate — would be a thin, named-in-appearance-only wrapper around the same single loop |
| LangGraph for neither, keep the original architectural reasoning as final | Ignores a legitimate category of demonstrated need (the interview/role itself) that the original reasoning never accounted for |
| A full v1-style single graph spanning both services | Would directly contradict ADR-005's and ADR-007's already-resolved decision to split understanding() and narration() into separately deployable services |
| Rewrite narrate()'s public contract to expose the graph's internal state shape | Unnecessary coupling — callers (app.py, tests) have no reason to know or depend on how the retry loop is implemented internally |

---

## Revisit triggers

- **`understanding()`'s loop gains genuine multi-node branching** (e.g. a distinct recovery
  strategy per failure mode, closer to v1's progressively-broadening-region retry) — would
  reopen Step 2's reasoning with a real coordination problem behind it, not just external
  preference.
- **`narration()`'s graph needs to coordinate with `understanding()`'s state** (e.g. clarify()'s
  still-unimplemented query_id/session-store design, ADR-005's Accompanying decisions) — would
  raise the same "does this need to be one graph across a service boundary" question ADR-005 and
  ADR-007 already answered no to, and that answer would need to be re-examined, not assumed to
  still hold.
