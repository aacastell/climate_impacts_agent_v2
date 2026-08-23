# ADR-003: Infrastructure Provisioning

**Status:** Accepted
**Depends on:** ADR-001 (static delivery via S3 + CloudFront), ADR-002 (React/TypeScript
frontend)
**Scope:** How AWS resources for this system — frontend delivery today, the API tier and any
data-pipeline infrastructure later — are defined and applied. Does not cover CI/CD pipeline
design (which stage invokes the provisioning tool, and when) or the API tier's own
architecture.

---

## Context

This system is not one component. The frontend, the API tier, and eventually the ISIMIP data
pipeline all need AWS resources, and those resources need to reference each other — an IAM
role scoped to exactly the bucket CloudFront reads from, a CloudFront origin pointed at
wherever the API tier ends up living, and so on. ADR-001 already named this as an open item:
*"if a NASA infrastructure team with existing IaC and CI/CD standards takes ownership, this
decision is reinforced. If not, the pipeline work falls to us."*

Two facts about the team drive this decision, in addition to the ones ADR-002 already
recorded:

- **Team fluency is Python-first.** TypeScript was chosen for the frontend in ADR-002 for a
  specific, narrow reason — hiring depth on a layer expected to be handed to other engineers.
  The frontend is explicitly the component most likely to change hands first; infrastructure
  and the data pipeline are not.
- **The data pipeline is deterministic Python** (repo README: "Computed facts | ISIMIP
  outputs, deterministic Python"). Whatever provisions the infrastructure around that pipeline
  sits immediately next to it.

Deployment target is a new commercial (non-GovCloud) AWS account, greenfield. No second cloud
provider appears anywhere in this project's stated requirements.

---

## Decision

**AWS CDK, in Python, as the infrastructure-as-code tool for every AWS resource this system
needs.**

---

## How we got there

### Step 1 — Manual console configuration is not a candidate for the standing pipeline

Useful once, by hand, to build a mental model of what a bucket policy or a CloudFront origin
actually does. Not viable as the repeatable path: the moment a second component needs to be
*connected* to the first — an IAM trust relationship, a multi-origin routing rule — manual
setup stops being a record of anything. Six months later nobody can reconstruct which console
screen a given permission came from. This is a reproducibility and reviewability problem, not
a speed problem.

**→ Some form of infrastructure-as-code, applied through CI rather than a person's local
credentials — same ephemeral-compute principle as the frontend build in ADR-002.**

### Step 2 — Cloud-agnostic (Terraform) or AWS-native (CloudFormation/CDK)?

Terraform's appeal is real: HCL is a mature, widely known DSL, and a Terraform codebase can in
principle target a different cloud without a rewrite.

Weighed against what this project has actually decided elsewhere: ADR-001 commits to
CloudFront, ACM, and WAF specifically — AWS-managed services with no equivalent API on another
cloud. The *application's architecture* is not portable today regardless of which IaC tool
describes it, so Terraform's abstraction currently buys syntax-level portability without
architecture-level portability. Its real, non-hypothetical costs are immediate: HCL as a new
language to learn, and a state backend (S3 + DynamoDB lock table) that is itself
infrastructure someone has to provision and keep available before anything else can be
deployed.

**Rejected for now** — no second-cloud requirement exists in this project's own documents.
Revisit trigger below.

### Step 3 — Raw CloudFormation or CDK?

Raw CloudFormation (YAML/JSON) needs no additional tooling — it is the substrate everything
else in this space compiles down to regardless. But it has no loops, no functions, and no
types; expressing "one role per bucket, generated for N buckets" means hand-duplicated YAML
blocks.

CDK is a real programming language wrapping CloudFormation: it compiles to CloudFormation
templates, so it inherits CloudFormation's stack/changeset/rollback model exactly, while adding
loops, functions, static types, and reusable, composable constructs.

**→ CDK.** The wrapping is worth it as soon as a system has more than a handful of resources
that reference each other — which is precisely the "components have to be executed and
connected" problem this ADR exists to solve.

### Step 4 — Which CDK language: TypeScript or Python?

The reflexive move is "ADR-002 chose TypeScript, stay consistent." That copies ADR-002's
*answer* rather than its *reasoning*. ADR-002's governing criterion was hiring depth for an
indefinitely-owned layer, applied to the frontend specifically because the frontend is the
layer most likely to be handed to an incoming engineer. Applying the same criterion correctly
here means asking who owns *this* layer — and the answer is a Python-first team, maintaining
infrastructure that sits directly beside a Python data pipeline. A contributor fluent in the
data pipeline is, for free, fluent in the infrastructure around it. Cloud and data
infrastructure hiring also skews at least as Python-heavy as TypeScript-heavy — the
hiring-depth argument does not clearly favor TypeScript for this layer the way it did for
frontend UI work.

**Cost being accepted:** CDK's Python bindings trail the TypeScript bindings slightly on
day-one availability of brand-new L2 constructs, since TypeScript was CDK's original,
first-class language. The gap is narrow and has been narrowing steadily; judged worth
accepting against the fluency and single-language-with-the-pipeline argument.

**→ Python.**

### Step 5 — Considered and rejected: CDKTF

CDK for Terraform offers CDK's programming-language ergonomics while generating Terraform
configuration instead of CloudFormation — on paper, "CDK ergonomics, cloud-agnostic," which is
what a reader tempted by both Step 2 and Step 3's winners might reach for next.

**Rejected.** It compounds the learning curve rather than removing it: underneath the CDK
syntax it still requires learning Terraform's state/backend/provider model, on a newer,
smaller-community layer than either CDK-for-CloudFormation or Terraform itself. Step 2 already
found no live multi-cloud requirement — paying a compounded cost for a still-hypothetical
benefit doesn't clear the bar.

---

## Accompanying decisions

- **The CDK app lives in its own top-level directory** (`infra/`), separate from `frontend/`
  — a distinct dependency tree (Python, not the frontend's npm tree) and a distinct deploy
  cadence. Infrastructure changes rarely and carries more risk per change (a VPC or IAM
  policy); frontend/content deploys happen often and are cheap to reverse. One pipeline for
  both was flagged as a common mistake and is deliberately avoided.
- **Applied via CI, never from a developer's laptop** — mirrors the frontend build's ephemeral
  compute model. Provisioning AWS resources should not depend on any one person's local
  credentials being present and correctly configured.

---

## Consequences

**Accepted:**

- Two languages live in this repo — TypeScript for the frontend, Python for infrastructure —
  rather than one throughout. Judged acceptable because ownership genuinely splits along that
  same line: a frontend contributor is not expected to routinely touch CDK stacks, or vice
  versa.
- CDK's AWS-only scope is accepted deliberately, not overlooked. If a second cloud becomes a
  real requirement, this decision does not flex — it is void, and Step 2 is redone from
  scratch (see revisit trigger).
- Python CDK's marginally slower day-one access to brand-new AWS construct coverage, relative
  to TypeScript.

**Gained:**

- One language, Python, spans the data pipeline and the infrastructure that runs it — fluency
  in one is fluency in both, with no translation layer.
- CDK's typed, composable construct model replaces hand-duplicated YAML for any resource graph
  with more than a couple of cross-references — the direct answer to the "components must be
  executed and connected" problem this ADR was raised to solve.
- CloudFormation's stack model underneath CDK gives atomic rollback and drift detection for
  free: a failed deploy does not leave the account in a half-updated, undocumented state.

---

## Rejected options, summary

| Option | Reason |
|---|---|
| Manual console configuration | Not reproducible or reviewable once components must reference each other |
| Terraform | No live multi-cloud requirement in this project's stated scope; state-backend and new-DSL costs are immediate and real, portability benefit is not |
| Raw CloudFormation | No loops, functions, or types; unwieldy once resources cross-reference each other |
| CDKTF | Compounds Terraform's learning curve with CDK's rather than replacing either; still no live multi-cloud requirement to justify it |
| CDK in TypeScript | Copies ADR-002's answer rather than its reasoning; the layer's actual owners are Python-first and sit next to a Python data pipeline |

---

## Revisit triggers

- **A second cloud provider becomes a real, stated requirement** (not hypothetical) — reopens
  Step 2; Terraform or CDKTF becomes worth its switching cost at that point.
- **An infra/data hire with strong TypeScript and weak Python fluency becomes this layer's
  primary owner** — reopens Step 4 on the same hiring-depth grounds ADR-002 used for the
  frontend.
- **A NASA infrastructure team with existing IaC standards takes ownership** — the open item
  flagged in ADR-001. This entire ADR is superseded by whatever standard they already run,
  not merged with it.
