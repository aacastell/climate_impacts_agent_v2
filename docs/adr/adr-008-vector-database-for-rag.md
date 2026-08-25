# ADR-008: Vector Database for RAG Retrieval — Deferred by Design

**Status:** Accepted
**Depends on:** ADR-007 (narration verification gate — establishes RAG's service boundary and
scope; explicitly left "the specific vector database/embedding technology" open)
**Scope:** Whether, and under what condition, `narration()`'s RAG retrieval should move off
in-process cosine similarity onto a real vector database, and what that would concretely look
like once justified. Does not reopen ADR-007's decision that RAG is bundled with narration, not
a separate service.

---

## Context

`services/narration/retrieval.py` retrieves literature passages via plain in-memory cosine
similarity over precomputed embeddings (embeddings computed once at ingestion, only the query is
embedded per request). The corpus (`services/narration/CORPUS_SOURCES_CANDIDATES.md`) is 15
curated NASA/agronomic sources, chunking down to on the order of a few hundred passages once
curated — nowhere near the scale a vector database earns its keep at. The module's own docstring
already states this explicitly: introducing OpenSearch/pgvector ahead of a demonstrated need
would repeat the exact premature-infrastructure pattern this project has already rejected
elsewhere (Airflow and Kubeflow, both ADR-006).

The question this ADR resolves isn't "vector DB or not" in the abstract — it's whether to build
one now, and if not, whether "we didn't need it" is a real technical position or just an
unexamined default. The latter is indistinguishable from cargo-culting in the other direction:
skipping real infrastructure without being able to say precisely when it *would* become
necessary is no more defensible than adopting it without need.

---

## Decision

**No vector database now.** In-process cosine similarity over precomputed embeddings stays.
This ADR records the specific, empirical trigger condition for revisiting that, and the concrete
design that would be adopted at that point — so the deferral is a plan, not an absence of one.

---

## How we got there

### Step 1 — Why not now

Corpus size and query volume are both far below where linear scan's O(n) cost matters. The
retrieval step's own latency has never been the bottleneck in any of this project's real
benchmarking (`understanding()`'s Bedrock round-trip and `narration()`'s generate+verify retry
chain both dominate end-to-end latency by a wide margin). Building indexing/ingestion
infrastructure against a problem that doesn't exist yet trades real engineering time for a
capability nothing in the system currently needs — the same reasoning ADR-006 already applied to
Airflow (no second recurring pipeline to justify it) and Kubeflow (no training loop yet to
orchestrate).

### Step 2 — What the actual trigger is

Not corpus size alone — the trigger is empirical, not a round number picked in advance:
**benchmark linear-scan retrieval latency against the actual latency budget, and cross when it's
measured to be the bottleneck**, not before. As a rough proxy, corpus growth from curated
tens/hundreds of passages into the low thousands is where that crossover typically starts to
matter — worth re-benchmarking at that point rather than assumed.

### Step 3 — Index choice, once triggered: HNSW over IVF

`narration()`'s corpus access pattern is read-heavy with infrequent writes (mirrors ISIMIP data's
own "changes rarely" property, ADR-006) at moderate scale. HNSW gives a better recall/latency
tradeoff than IVF at that access pattern; IVF's advantages (cheaper index builds, better behavior
under frequent re-indexing) pay off more on corpora that are both much larger and much more
frequently updated than this one would plausibly become.

### Step 4 — Hybrid retrieval, not pure dense

Pure embedding similarity misses exact-term matches that matter in scientific literature — a
specific gene name, a specific numeric threshold mentioned in prose (e.g. a cited heat-stress
temperature). Combining dense (embedding) retrieval with sparse (BM25) retrieval and fusing
results is standard practice in production RAG for exactly this failure mode, and would be part
of the design adopted at trigger point, not an afterthought.

### Step 5 — Ingestion becomes a real, versioned pipeline

Today's corpus curation is a one-time, human-reviewed step (`services/narration/corpus.py`'s own
docstring). A real vector-DB-backed retrieval layer needs ingestion to be a re-runnable pipeline,
not a one-shot script — an embedding-model upgrade requires re-embedding the entire corpus, so
chunk → embed → upsert has to be idempotent and repeatable. This is the same fetch/process
separation already established for ISIMIP data (ADR-006), applied to corpus ingestion instead of
climate/crop data.

### Step 6 — Retrieval quality needs its own metric, separate from ADR-007's verification gate

Today, a retrieval regression has no dedicated signal — it would only surface indirectly, as
narration content drifting and (maybe) tripping ADR-007's verification gate, which is measuring a
different thing (consistency with the held-out yield projection, not retrieval relevance). A real
vector-DB-backed retrieval layer needs its own recall@k metric against a held-out set of known
question → relevant-passage pairs, so a retrieval problem is caught as a retrieval problem, not
misdiagnosed as a generation or verification problem.

---

## Accompanying decisions

- **Evaluate Bedrock Knowledge Bases first, before hand-rolling.** It's the managed AWS-native
  wrapper around steps 3-5 (OpenSearch Serverless or Aurora pgvector underneath, managed
  chunking/ingestion) — the lower-effort starting point once the trigger in Step 2 is actually
  met. Hand-rolling is justified only once its limits are actually hit: tighter control over
  chunking strategy for domain-specific scientific text, cost at real scale, or avoiding
  vendor lock-in on the retrieval layer specifically.
- **If hand-rolled instead, the real candidates are:** OpenSearch Serverless with a vector engine
  (AWS-native, real per-OCU floor cost, not free at rest); Aurora Serverless v2 + pgvector
  (relational-familiar, real ACU floor cost); or a self-hosted engine (Qdrant/Chroma) as another
  container in the existing ECS cluster (no new managed-service line item, but more operational
  surface than either managed option).
- **`retrieve()`'s function signature stays the interface boundary.** Whatever gets adopted at
  trigger point swaps in behind the same signature `services/narration/retrieval.py` already
  exposes — same "replaceable behind a stable interface" pattern ADR-005 already established for
  `understanding()`'s model client.
- **This is not cost-neutral, unlike other deferred-and-later-adopted infrastructure in this
  project.** `understanding()`'s planned fine-tuned-model swap rides on Fargate capacity already
  paid for regardless of which model backs it. A vector database has no equivalent existing floor
  to land on — every option above is a genuinely new recurring cost line, however modest, not an
  optimization of an existing one.

---

## Consequences

**Accepted:**

- Retrieval quality has no dedicated metric today — a retrieval regression currently has no
  direct signal and would only be caught indirectly, if at all, through narration output quality.
- The trigger condition (Step 2) requires someone to actually benchmark linear-scan latency
  periodically as the corpus grows; it doesn't fire itself.

**Gained:**

- No infrastructure exists that nothing currently needs — corpus curation and retrieval stay as
  simple as the actual current scale warrants.
- A concrete, specific plan (index type, hybrid retrieval, versioned ingestion, eval metric,
  managed-vs-hand-rolled sequencing) already exists for when the trigger is met, rather than
  needing to be designed from scratch under production pressure or, worse, skipped entirely
  because "we never decided what we'd do here."

---

## Rejected options, summary

| Option | Reason |
|---|---|
| Add a vector database now, at current corpus size | Cargo-cult infrastructure — no demonstrated need; the same anti-pattern ADR-006 already rejected for Airflow and Kubeflow |
| Defer the decision with no concrete trigger or design | Indistinguishable from just not having thought about it — doesn't survive "why not?" in review |
| Pure dense retrieval only, even once scaled | Misses exact-term matches that matter in scientific prose (gene names, cited thresholds); hybrid dense+sparse outperforms pure dense in production RAG |
| IVF index over HNSW, once triggered | Worse recall/latency tradeoff for this corpus's actual access pattern (moderate size, read-heavy, infrequent updates) |
| Hand-roll ingestion and indexing from day one at trigger point | Bedrock Knowledge Bases is the lower-effort managed starting point; hand-rolling is justified only once its specific limits are actually hit |

---

## Revisit triggers

- **Benchmarked linear-scan retrieval latency exceeds `narration()`'s actual latency budget** —
  the real trigger condition from Step 2, not corpus size read in isolation.
- **Corpus grows from curated tens/hundreds of passages into the low thousands or beyond.**
- **RAG needs to serve a consumer beyond `narration()`** — this would also reopen ADR-007's
  service-boundary decision, not just this one.
- **Real production query logs exist**, giving Step 6's recall@k eval set something genuine to
  be built from instead of a synthetic stand-in.
