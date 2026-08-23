#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.frontend_hosting_stack import FrontendHostingStack
from stacks.frontend_build_project_stack import FrontendBuildProjectStack

app = cdk.App()

hosting = FrontendHostingStack(app, "ClimateImpactsFrontendHosting")

FrontendBuildProjectStack(
    app,
    "ClimateImpactsFrontendBuildProject",
    bucket=hosting.bucket,
    distribution=hosting.distribution,
)

app.synth()
