# Infrastructure

AWS CDK, Python, per [ADR-003](../docs/adr/adr-003-infrastructure-provisioning.md).

## Setup

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

Each Python component in this repo gets its own venv, scoped to its own directory — this one
is not shared with anything else, same as `frontend/`'s `node_modules` isn't.

**Node is also required**, even though this is a Python project: the CDK CLI (`aws-cdk`, an
npm package) is what actually reads this app and talks to CloudFormation — `aws-cdk-lib` is
only the Python bindings it talks to underneath, via `jsii`, which shells out to Node. `nvm use`
from this directory picks up the pinned version (`.nvmrc`, same version as `../frontend/.nvmrc`).
**jsii fails with a cryptic `Unexpected token '??='` error if the active Node is too old** —
that's the symptom, not the cause; check `node -v` first if `cdk` commands error out
unexpectedly. This also matters across separate terminal sessions/commands, not just once —
`nvm use` only affects the shell it's run in.

## Commands

```sh
npx aws-cdk synth      # render the CloudFormation templates
npx aws-cdk diff        # compare against what's currently deployed
npx aws-cdk deploy      # actually create/update AWS resources — needs credentials
```

**`synth` now needs valid AWS credentials too**, not just `deploy`/`diff` — a change from
before. `app.py` resolves `CDK_DEFAULT_ACCOUNT`/`CDK_DEFAULT_REGION` at synth time and passes
them explicitly to every stack, because the WAF stack's cross-region reference (below) requires
every stack in the reference to have a known account and region up front; an environment-agnostic
stack can't be one end of that link. Run `aws sso login --profile dev` first if a command fails
with a `CDK_DEFAULT_ACCOUNT` `KeyError`.

```sh
python -m pytest tests/ -v
```

## What's here

**`stacks/frontend_hosting_stack.py`** — the S3 bucket + CloudFront distribution ADR-001
decided on. Origin access control (not the legacy OAI pattern), a CloudFront Function for SPA
fallback routing, and a second CloudFront Function for security headers — both named in
ADR-001 directly.

**Deliberately not included: a custom domain and ACM certificate.** This is a portfolio
project with no NASA domain to point at — a self-issued placeholder domain would misrepresent
that as settled, so the distribution is only ever reached at its `*.cloudfront.net` address.

**`stacks/frontend_waf_stack.py`** — the WAF web ACL ADR-001 flagged as an open item, now
closed. Scoped to `CLOUDFRONT`, deployed to **us-east-1 unconditionally** — that's not this
app's home region, it's a hard requirement of WAFv2 web ACLs scoped to CloudFront, which are
only creatable via the us-east-1 API regardless of where anything else lives. `app.py` wires
its ARN into `FrontendHostingStack` (deployed in the profile's own region) via CDK cross-region
references, which is why both stacks now need an explicit `env` — see the `synth` note above.

Every rule — three AWS Managed Rule Groups (Common, Known Bad Inputs, IP Reputation) plus a
2000-requests-per-5-minutes-per-IP rate limit — starts in **Count mode, not Block**. There is
no production traffic yet to tune against; count mode surfaces what *would* be blocked in
CloudWatch metrics and sampled requests before any real request is ever dropped. Flipping a
rule to Block once that's confirmed clean is a deliberate follow-up, not a gap.

**`stacks/frontend_build_project_stack.py`** — an AWS CodeBuild project that builds the
frontend and uploads it to the bucket above, so that work runs on AWS compute instead of a
laptop. It runs the exact same scripts a human would (`scripts/build-frontend.sh`,
`scripts/upload-frontend.sh`, `scripts/invalidate-cache.sh`, via `../frontend/buildspec.yml`
— scoped under `frontend/`, not repo root, since this builds the frontend specifically, not
"the repo") rather than duplicating that logic — CodeBuild is just another caller of it.

This stack needs two things:

- **The GitHub repo it pulls from**, passed as CDK context. `scripts/provision-infra.sh`
  already supplies this (with real defaults baked in — see that script) — deploy via that,
  not a raw `cdk deploy` call.
- **A one-time GitHub connection authorized for this AWS account**, before CodeBuild can pull
  *any* GitHub source, public or private. Not part of this stack (it's an account-level,
  interactive authorization, not something CDK can create unattended) — set up via the
  CodeBuild console (Source credentials) or `aws codebuild import-source-credentials`. Already
  done for this project.

Its IAM role is scoped narrowly on purpose — S3 read/write on just this one bucket,
`cloudfront:CreateInvalidation` on just this one distribution, nothing broader. Verified by
inspecting the synthesized template, not assumed.

## Deploying

Both stacks deploy together, in one command: `../scripts/provision-infra.sh`, which runs
`cdk deploy --all`. One more stack later doesn't mean a new script — add it in `app.py` and
this picks it up automatically; CloudFormation only changes what actually differs per stack.

Both stacks are live — this has actually been run, not just written. Re-running is safe:
`cdk deploy` diffs against what's deployed and only changes what's actually different.
