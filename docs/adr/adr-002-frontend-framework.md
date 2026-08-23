# ADR-002: Frontend Framework

**Status:** Accepted
**Depends on:** ADR-001 (static delivery via S3 + CloudFront)
**Scope:** The client-side application. Does not cover the API tier.

---

## Context

ADR-001 established that the interface is delivered as static files. That constrains this
decision but does not settle it: several toolchains produce static output.

Two facts about ownership drive the choice:

- **The team maintains this system indefinitely.** There is no handover date after which the
  codebase stops being ours.
- **The stack should optimise for hiring depth.** People may be hired or rotated onto this
  work, so the question is not what the current team is fastest with, but what an incoming
  engineer is most likely to already know.

The application itself is modest: one view, a text input, two maps, a narration panel, and
one API call per query. No persistent conversation state.

---

## Decision

**React with TypeScript, built with Vite, using MapLibre GL JS for map rendering.**

---

## How we got there

### Step 1 — Streamlit is not a candidate

The existing prototype is Streamlit, and it is worth recording precisely why it cannot carry
forward, because the reason is structural rather than aesthetic.

Streamlit is a server-rendered application with a persistent WebSocket connection. The Python
script runs on a server; on every interaction it re-executes and the server pushes the
resulting UI down the connection. There is no build output — no HTML file, no JS bundle —
because the interface is generated per session, live.

That is not a mismatch of file formats. It is the opposite branch of the delivery decision
already taken in ADR-001: long-running server, persistent connection, per-user state, nothing
to place in a bucket. (It is also why App Runner would not host it — App Runner does not
support WebSockets — leaving Fargate or EC2 as its realistic homes.)

Retaining Streamlit means reopening ADR-001 and accepting always-warm compute. That trade was
considered and rejected: it would be choosing the hosting model to suit a framework the team
already knows, rather than choosing both against the requirements.

### Step 2 — Python-to-static tools rejected

Reflex, PyScript, and Panel in WASM mode all produce static bundles from Python source, and
would have let the team stay in one language.

Rejected on the maintenance horizon. These are small ecosystems. On an indefinite ownership
horizon, the operative risk is not the initial build — it is the build that breaks three years
in, against a dependency nobody upstream has documented. Ecosystem size stops being a
preference and becomes a risk register item.

The Pyodide-based options carry a second problem: they ship a multi-megabyte Python runtime to
every first-time visitor. Against a requirement of "anyone in the world," including users on
constrained mobile connections, that is a poor trade for developer convenience.

### Step 3 — Among JavaScript frameworks

| Option | Assessment |
|---|---|
| **React** | Largest developer pool by a wide margin; deepest third-party ecosystem; most candidates with directly comparable experience. Historically the most ecosystem churn. |
| **Vue** | Stable, gentler learning curve, less churn. Materially smaller hiring pool. |
| **Svelte** | Thinnest runtime, smallest bundles, least ceremony. Smallest and youngest ecosystem of the three. |
| **No framework (plain TS)** | Arguably proportionate to a one-view app, and zero framework churn by construction. Rejected because every new hire would learn bespoke conventions instead of transferable ones — the opposite of the stated criterion. |

On hiring depth specifically, React wins decisively. Vue and Svelte are good frameworks
rejected on ecosystem size alone, not on technical merit.

### Step 4 — The portability argument

React also holds up on the axis we cannot foresee.

If the delivery model ever changes — most plausibly because NASA wants answer URLs to be
shareable and indexable, the revisit trigger flagged in ADR-001 — the move is into a
React-based server-rendering framework such as Next.js. Component code, state logic, and map
integration largely carry over. The same change from a Python-to-static tool, or from a
no-framework codebase, is closer to a rewrite.

This argument is independent of hiring depth and, on an indefinite horizon, arguably stronger.

---

## Accompanying decisions

**TypeScript over plain JavaScript.** On a multi-year maintenance horizon this has a larger
payoff than the framework choice itself, and it costs nothing in hiring depth — TypeScript is
the default expectation in React roles.

**Vite as the build tool.** The current mainstream default for new React projects, chosen for
the same reason as React: an incoming engineer recognises it immediately.

**MapLibre GL JS for maps.** Open source with no licensing constraints, handles vector tiles
and GeoJSON, and is framework-agnostic. Note that map work is JavaScript-native regardless of
framework choice — Python wrappers exist but add a translation layer to debug through when
projections or tile boundaries misbehave. The maps put this project in the JS ecosystem
independently of everything above.

---

## Consequences

**Accepted:**

- The team writes TypeScript rather than Python for the interface layer.
- React's ecosystem size is also a liability: it is easy to accumulate dozens of transitive
  dependencies for a one-view application. On a public NASA-branded site subject to security
  scanning, each is a future CVE and a future breaking upgrade. **A deliberately small
  dependency tree is a standing constraint**, worth more here than any convenience library.
- **The React major version is pinned and upgraded deliberately**, on our schedule rather than
  because a transitive dependency forced it. React has moved its ecosystem before and will
  again.

**Gained:**

- Hiring depth, per the stated criterion.
- Headroom on UI complexity — additional views, client-side routing, comparison panels, saved
  queries — without a framework change.
- A migration path to server-side rendering that preserves most of the codebase, should
  ADR-001's revisit trigger fire.

---

## Revisit triggers

- **SEO or link-preview requirement appears.** Framework survives; the build target changes
  (Vite SPA → Next.js or equivalent). ADR-001 is reopened first.
- **Team composition changes such that hiring depth is no longer the governing criterion.**
- **The application stays permanently at one view with negligible state.** In that case the
  no-framework option, rejected above, becomes worth re-examining — though the switching cost
  by then likely exceeds the benefit.
