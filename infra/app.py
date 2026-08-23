#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.frontend_hosting_stack import FrontendHostingStack
from stacks.frontend_build_project_stack import FrontendBuildProjectStack

app = cdk.App()

hosting = FrontendHostingStack(app, "ClimateImpactsFrontendHosting")

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
    )

app.synth()
