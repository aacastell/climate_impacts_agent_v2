import aws_cdk as cdk
from aws_cdk import aws_s3 as s3
from aws_cdk.assertions import Match, Template
from constructs import Construct

from stacks.isimip_fetch_build_project_stack import IsimipFetchBuildProjectStack


class _BucketHarness(cdk.Stack):
    """A bucket the build-project stack can reference, standing in for
    IsimipDataBucketStack the way this stack is actually wired in app.py."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.bucket = s3.Bucket(self, "TestBucket")


def _template() -> Template:
    app = cdk.App()
    bucket_stack = _BucketHarness(app, "TestBucketHarness")
    stack = IsimipFetchBuildProjectStack(
        app,
        "TestIsimipFetchBuildProjectStack",
        bucket=bucket_stack.bucket,
        github_owner="example-owner",
        github_repo="example-repo",
    )
    return Template.from_stack(stack)


def test_project_uses_pipeline_buildspec():
    _template().has_resource_properties(
        "AWS::CodeBuild::Project",
        {"Source": Match.object_like({"BuildSpec": "pipeline/buildspec.yml"})},
    )


def test_project_has_no_webhook():
    """Manually triggered only — see ADR-006 Step 7. A webhook here would
    mean re-fetching on every push to main, which this pipeline's own
    update cadence doesn't call for."""
    resources = _template().to_json()["Resources"]
    assert not any(r["Type"] == "AWS::CodeBuild::ProjectWebhook" for r in resources.values())


def test_project_has_fixed_predictable_name():
    _template().has_resource_properties(
        "AWS::CodeBuild::Project",
        {"Name": "ClimateImpactsIsimipFetch"},
    )


def test_compute_is_upgraded_past_the_low_throughput_default():
    """SMALL (the CDK/CodeBuild default) is the lowest network-throughput
    tier — untested against this project's real transfer volume (tens of
    GB). MEDIUM is the deliberate minimum here, not SMALL."""
    _template().has_resource_properties(
        "AWS::CodeBuild::Project",
        {"Environment": Match.object_like({"ComputeType": "BUILD_GENERAL1_MEDIUM"})},
    )


def test_timeout_is_generous_past_the_untested_default():
    """Default CodeBuild timeout is 60 minutes — untested against ~43 GB
    across 12 fetch stages at the time this was set. Explicit and
    generous, not left at the default."""
    _template().has_resource_properties(
        "AWS::CodeBuild::Project",
        {"TimeoutInMinutes": 240},
    )
