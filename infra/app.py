#!/usr/bin/env python3
import json
import os
from pathlib import Path

import aws_cdk as cdk

from stacks.api_stack import ApiStack
from stacks.frontend_build_project_stack import FrontendBuildProjectStack
from stacks.frontend_hosting_stack import FrontendHostingStack
from stacks.frontend_waf_stack import FrontendWafStack
from stacks.isimip_data_bucket_stack import IsimipDataBucketStack
from stacks.model_services_stack import ModelServicesStack
from stacks.pipeline_step_build_project_stack import PipelineStepBuildProjectStack

app = cdk.App()

# CDK sets these from the resolved credentials/profile (e.g. the "dev" SSO
# profile) before this file runs. Both are needed, explicitly, on every
# stack below: cross-region references (WAF in us-east-1, everything else
# in the profile's own region) only work between stacks with a known
# account and region at synth time — an env-agnostic stack can't be a
# target or source of one.
account = os.environ["CDK_DEFAULT_ACCOUNT"]
home_region = os.environ["CDK_DEFAULT_REGION"]

# A WAFv2 web ACL scoped to CLOUDFRONT is only creatable via the us-east-1
# API, regardless of which region the rest of this app deploys to — see
# FrontendWafStack's docstring.
waf = FrontendWafStack(
    app,
    "ClimateImpactsFrontendWaf",
    env=cdk.Environment(account=account, region="us-east-1"),
    cross_region_references=True,
)

isimip_data = IsimipDataBucketStack(
    app,
    "ClimateImpactsIsimipDataBucket",
    env=cdk.Environment(account=account, region=home_region),
)

# understanding() and narration()'s real ECS/Fargate infrastructure — see ModelServicesStack's
# own docstring for why these two specifically get scalable, persistent compute (ADR-005).
# Created before FrontendHostingStack (below) because that stack's /api/* CloudFront behavior
# needs ApiStack's RestApi construct, which needs these services' ALB DNS names first.
model_services = ModelServicesStack(
    app,
    "ClimateImpactsModelServices",
    isimip_data_bucket=isimip_data.bucket,
    env=cdk.Environment(account=account, region=home_region),
)

# The Lambda orchestration tier — ADR-005's resolved compute-topology decision. Points at
# ModelServicesStack's real ALB DNS names, never hardcoded, so this stack has no implicit
# assumption about where those services actually live.
api = ApiStack(
    app,
    "ClimateImpactsApi",
    isimip_data_bucket=isimip_data.bucket,
    understanding_url=f"http://{model_services.understanding_service.load_balancer.load_balancer_dns_name}",
    narration_url=f"http://{model_services.narration_service.load_balancer.load_balancer_dns_name}",
    env=cdk.Environment(account=account, region=home_region),
)

hosting = FrontendHostingStack(
    app,
    "ClimateImpactsFrontendHosting",
    web_acl_arn=waf.web_acl_arn,
    processed_data_bucket=isimip_data.bucket,
    api=api.api,
    env=cdk.Environment(account=account, region=home_region),
    cross_region_references=True,
)

github_owner = app.node.try_get_context("githubOwner")
github_repo = app.node.try_get_context("githubRepo")
if github_owner and github_repo:
    FrontendBuildProjectStack(
        app,
        "ClimateImpactsFrontendBuildProject",
        bucket=hosting.bucket,
        distribution=hosting.distribution,
        github_owner=github_owner,
        github_repo=github_repo,
        env=cdk.Environment(account=account, region=home_region),
    )

    # Every fetch stage and every process field gets its own fully independent CodeBuild project —
    # see PipelineStepBuildProjectStack's docstring for why (replaces a single shared project
    # whose DVC_TARGET-override triggers caused real, unwanted cross-stage coupling). This
    # replaces the previous single ClimateImpactsIsimipFetchBuildProject stack; that old CodeBuild
    # project (ClimateImpactsIsimipFetch) is no longer managed here and needs manual cleanup
    # (`aws codebuild delete-project`) once the new projects are confirmed working — not deleted
    # automatically as a side effect of this change.
    bucket_name = isimip_data.bucket.bucket_name

    FETCH_STEPS = {
        "ClimateImpactsFetchTasBaseline": f"python -m climate_pipeline.fetch.climate --variable tas --window baseline --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchTasFuture": f"python -m climate_pipeline.fetch.climate --variable tas --window future --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchTasPreindustrial": f"python -m climate_pipeline.fetch.climate --variable tas --window preindustrial --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchPrBaseline": f"python -m climate_pipeline.fetch.climate --variable pr --window baseline --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchPrFuture": f"python -m climate_pipeline.fetch.climate --variable pr --window future --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchMaizeBaseline": f"python -m climate_pipeline.fetch.agriculture --crop maize --window baseline --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchMaizeFuture": f"python -m climate_pipeline.fetch.agriculture --crop maize --window future --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchSpringWheatBaseline": f"python -m climate_pipeline.fetch.agriculture --crop spring_wheat --window baseline --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchSpringWheatFuture": f"python -m climate_pipeline.fetch.agriculture --crop spring_wheat --window future --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchSoyBaseline": f"python -m climate_pipeline.fetch.agriculture --crop soy --window baseline --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchSoyFuture": f"python -m climate_pipeline.fetch.agriculture --crop soy --window future --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchRiceBaseline": f"python -m climate_pipeline.fetch.agriculture --crop rice --window baseline --bucket {bucket_name} --manifest-dir manifests",
        "ClimateImpactsFetchRiceFuture": f"python -m climate_pipeline.fetch.agriculture --crop rice --window future --bucket {bucket_name} --manifest-dir manifests",
    }

    PROCESS_STEPS = {
        f"ClimateImpactsProcess{field.title().replace('_', '')}": (
            f"python -m climate_pipeline.process.run --field {field} --bucket {bucket_name} "
            "--manifest-dir manifests --work-dir work --out-dir processed_global"
        )
        for field in (
            "tas",
            "pr",
            "consecutive_dry_days",
            "extreme_heat_days",
            "maize",
            "spring_wheat",
            "soy",
            "rice",
        )
    }
    # No field above knows or cares about global warming level — GWL is resolved separately, only
    # at query time (timecode()), from its own dedicated step. See
    # climate_pipeline/process/gwl_table.py and run.py's module docstring.
    PROCESS_STEPS["ClimateImpactsProcessGwlYearTable"] = (
        f"python -m climate_pipeline.process.gwl_table --bucket {bucket_name} "
        "--manifest-dir manifests --work-dir work"
    )

    # RAG corpus source fetch — same fetch/process separation as ISIMIP (ADR-006), same
    # per-component independence as everything else tonight. Real candidate sources found via web
    # search (see pipeline/climate_pipeline/fetch/CORPUS_SOURCES.json,
    # services/narration/CORPUS_SOURCES_CANDIDATES.md) — this fetches raw content only, never
    # curates it into the actual retrievable corpus (services/narration/corpus.py stays a human
    # review step).
    _corpus_sources = json.loads((Path(__file__).parent.parent / "pipeline/climate_pipeline/fetch/CORPUS_SOURCES.json").read_text())
    CORPUS_FETCH_STEPS = {
        f"ClimateImpactsFetchCorpus{source['id'].title().replace('_', '')}": (
            f"python -m climate_pipeline.fetch.corpus --source-id {source['id']} --bucket {bucket_name} --manifest-dir manifests"
        )
        for source in _corpus_sources
    }

    for project_name, run_cmd in {**FETCH_STEPS, **PROCESS_STEPS, **CORPUS_FETCH_STEPS}.items():
        PipelineStepBuildProjectStack(
            app,
            f"{project_name}Stack",
            project_name=project_name,
            run_cmd=run_cmd,
            bucket=isimip_data.bucket,
            github_owner=github_owner,
            github_repo=github_repo,
            env=cdk.Environment(account=account, region=home_region),
        )

app.synth()
