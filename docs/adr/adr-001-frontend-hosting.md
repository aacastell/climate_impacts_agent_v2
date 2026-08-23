# ADR-001: Frontend Hosting

**Status:** Accepted
**Scope:** Delivery of the user-facing web interface only. Does not cover the API tier.

---

## Context

The interface is a single web page: a text input, two maps, and a narration panel. A user
submits a question; the system returns narration plus values used to shade the maps. Each
request is independent — there is no persistent conversation state.

Requirements bearing on this decision:

- Publicly accessible, unauthenticated, global audience
- NASA-branded custom domain with TLS
- A place to attach rate limiting and traffic controls (public + unauthenticated = unbounded
  request exposure)
- Deployed to a new commercial (non-GovCloud) AWS account, greenfield

---

## Decision

**Static delivery from S3 behind CloudFront, assembled and managed directly rather than
through AWS Amplify Hosting.**

---

## How we got there

### Step 1 — Does a server need to build the HTML per request?

This is the only question that separates static from dynamic delivery. It is *not* about
interactivity, JavaScript, API calls, or whether content differs between users. It is about
whether the HTML document leaving the server was assembled at request time.

Two conditions would force server-side rendering:

1. **Content must be present in the HTML source at delivery** — required when search engines
   or link-preview crawlers must read the content, since they do not execute JavaScript.
2. **The delivered document differs per user before any JavaScript runs** — sessions, auth
   gating, personalised content.

Neither applies. There is no requirement for individual answers to be indexable or to
generate link previews, and there is no per-user content. The narration and map shading
arrive via API calls after page load and are written into the live document by client-side
code; the HTML file itself is byte-identical for every visitor and every question.

**→ Static delivery. This eliminates the entire serverless-render and long-running-server
branch of the option space** (Lambda/API Gateway SSR, App Runner, ECS/Fargate, EKS, EC2,
Elastic Beanstalk, Lightsail). None of them was rejected on cost or scale — they were
rejected because the job they do is not a job this system has.

> **Caveat for future reviewers:** this conclusion depends entirely on condition (1). If NASA
> later wants answer URLs to be shareable and indexable — a Google result and a preview card
> for `/occitanie/maize/2C` — the answer flips and this ADR must be revisited.

### Step 2 — Which static delivery option?

**S3 REST endpoint, direct — rejected.**
Cannot serve a custom domain with our own TLS certificate. This is a functional blocker, not
a risk to be weighed. Additionally: no WAF attachment point, no edge caching (single-region
latency for a global audience), and every request billed as an origin request at S3's
internet egress rate.

**S3 website endpoint, direct — rejected.**
Same custom-domain and certificate blocker, and it serves over HTTP only — no TLS at all.
Disqualified before any other consideration.

Both options are technically capable of the throughput required; S3 sustains very high
request rates and a frequently-read object is not a hot-key problem in an object store. They
fail on capability, not on scale.

**→ S3 + CloudFront.** CloudFront supplies the custom domain and certificate, TLS
termination, global edge caching, the WAF attachment point, and — counterintuitively — lower
egress cost than S3 direct, since S3-to-CloudFront transfer is not charged.

### Step 3 — Managed (Amplify Hosting) or self-assembled?

Amplify Hosting runs on the same CloudFront + S3 substrate. It adds git-connected CI/CD,
per-pull-request preview environments, atomic deploys, one-click rollback, and
console-configured redirect rules. It costs fine-grained control of the CloudFront
distribution.

**Amplify Hosting — rejected.**
The deciding factor is control of the distribution: cache behaviours, function associations,
and in particular the option of a single distribution with multiple origins (`/` to the
bucket, `/api/*` to the compute tier, one domain, no CORS). Amplify makes that pattern
awkward. The convenience it offers is real but is a one-time saving on pipeline setup, while
the control constraint would persist for the life of the system.

**→ Self-assembled S3 + CloudFront.**

---

## Not a separate option: edge functions

Edge behaviour was considered as a third alternative and is not one. Both the managed and
self-assembled paths require the same capabilities:

- **SPA fallback routing.** With client-side routes, a direct visit, refresh, or shared link
  to `/occitanie/maize/2C` requests a path that does not exist in the bucket. Without a rule
  rewriting unmatched paths to `index.html`, S3 returns 404 — breaking precisely the action a
  user is most likely to take with a result worth keeping.
- **Security headers** (CSP, HSTS, X-Frame-Options), which a public NASA-branded site will be
  scanned for.

Amplify supplies these as console redirect rules; the self-assembled path supplies them as
CloudFront Functions. Same requirement, different packaging.

---

## Consequences

**Accepted:**

- We own the deployment pipeline, including atomic-deploy discipline: content-hashed asset
  filenames, assets uploaded before HTML. A naive bucket sync can serve a new `index.html`
  alongside a not-yet-uploaded JS bundle — a broken page that produces no error in any log.
- We write and maintain the CloudFront Functions for fallback routing and security headers.
- Custom domain and certificate are ours to wire. **The ACM certificate must be issued in
  `us-east-1`** regardless of where the rest of the system runs.

**Gained:**

- Single-distribution multi-origin routing remains available, keeping the frontend and API on
  one domain with no CORS layer.
- Full control of cache behaviours, which matters if map tiles are later served through the
  same distribution.
- WAF attaches directly, satisfying the traffic-ceiling requirement.

---

## Rejected options, summary

| Option | Reason |
|---|---|
| Lambda / API Gateway SSR | No server-side rendering requirement |
| Lambda@Edge SSR | Same |
| App Runner | Same; also no WebSocket support and does not scale fully to zero |
| ECS Fargate, ECS on EC2, EKS | Same; long-running compute for content that never changes |
| EC2 + ALB + ASG | Same; plus 24/7 cost, OS patching, single-region latency |
| Elastic Beanstalk, Lightsail | Same |
| S3 REST endpoint direct | No custom domain + TLS; no WAF; no edge caching |
| S3 website endpoint direct | HTTP only; no custom certificate |
| Amplify Hosting | Loss of CloudFront control, specifically multi-origin routing |

---

## Open items

- **Owner of the deployment pipeline.** If a NASA infrastructure team with existing IaC and
  CI/CD standards takes ownership, this decision is reinforced. If not, the pipeline work
  falls to us.
- **Whether the API shares this distribution** or sits on a separate subdomain with CORS.
  Deferred to the API tier design.

---

## Note on figures

This document deliberately contains no prices, rate limits, or quotas. Those change on a
schedule outside our control and go stale invisibly in a document like this. What is durable
is the *shape* of each cost — S3 bills storage, requests, and egress; CloudFront bills egress
and requests; long-running compute bills by time whether or not traffic arrives. Verify
current figures against AWS documentation at the time they are needed.

