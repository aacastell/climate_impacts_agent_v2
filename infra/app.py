#!/usr/bin/env python3
import os

import aws_cdk as cdk

from stacks.frontend_build_project_stack import FrontendBuildProjectStack
from stacks.frontend_hosting_stack import FrontendHostingStack
from stacks.frontend_waf_stack import FrontendWafStack
from stacks.isimip_data_bucket_stack import IsimipDataBucketStack
from stacks.isimip_fetch_build_project_stack import IsimipFetchBuildProjectStack

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

hosting = FrontendHostingStack(
    app,
    "ClimateImpactsFrontendHosting",
    web_acl_arn=waf.web_acl_arn,
    processed_data_bucket=isimip_data.bucket,
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

    IsimipFetchBuildProjectStack(
        app,
        "ClimateImpactsIsimipFetchBuildProject",
        bucket=isimip_data.bucket,
        github_owner=github_owner,
        github_repo=github_repo,
        env=cdk.Environment(account=account, region=home_region),
    )

app.synth()
