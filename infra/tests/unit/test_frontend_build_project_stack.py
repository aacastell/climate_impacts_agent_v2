import aws_cdk as cdk
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk.assertions import Match, Template
from constructs import Construct

from stacks.frontend_build_project_stack import FrontendBuildProjectStack


class _Harness(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.bucket = s3.Bucket(self, "TestBucket")
        self.distribution = cloudfront.Distribution(
            self,
            "TestDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.bucket)
            ),
        )


def _template() -> Template:
    app = cdk.App()
    harness = _Harness(app, "TestHarness")
    stack = FrontendBuildProjectStack(
        app,
        "TestFrontendBuildProjectStack",
        bucket=harness.bucket,
        distribution=harness.distribution,
        github_owner="aacastell",
        github_repo="climate_impacts_agent_v2",
    )
    return Template.from_stack(stack)


def test_build_uses_the_real_api_not_the_default_mock_client():
    # Real bug caught before it shipped: Vite bakes import.meta.env.VITE_* in at build time, not
    # runtime. Without VITE_USE_MOCK_API=false set here, every real deploy would silently keep
    # serving frontend/src/api/index.ts's default (MockApiClient, fully synthetic data) no matter
    # how real the backend infrastructure actually is.
    _template().has_resource_properties(
        "AWS::CodeBuild::Project",
        Match.object_like(
            {
                "Environment": Match.object_like(
                    {
                        "EnvironmentVariables": Match.array_with(
                            [Match.object_like({"Name": "VITE_USE_MOCK_API", "Value": "false"})]
                        )
                    }
                )
            }
        ),
    )


def test_build_uses_free_tier_eligible_small_compute():
    # Deliberate, not incidental — see the CodeBuild-cost conversation this was checked against
    # live: BUILD_GENERAL1_SMALL is the only CodeBuild compute size covered by AWS's free tier.
    # A future change to MEDIUM/LARGE here would quietly lose that coverage on every deploy.
    _template().has_resource_properties(
        "AWS::CodeBuild::Project",
        Match.object_like({"Environment": Match.object_like({"ComputeType": "BUILD_GENERAL1_SMALL"})}),
    )
