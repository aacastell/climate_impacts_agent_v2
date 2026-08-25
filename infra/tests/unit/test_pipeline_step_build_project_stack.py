import aws_cdk as cdk
from aws_cdk import aws_s3 as s3
from aws_cdk.assertions import Match, Template
from constructs import Construct

from stacks.pipeline_step_build_project_stack import PipelineStepBuildProjectStack


class _BucketHarness(cdk.Stack):
    """A bucket the build-project stack can reference, standing in for
    IsimipDataBucketStack the way this stack is actually wired in app.py."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.bucket = s3.Bucket(self, "TestBucket")


def _template(project_name: str = "ClimateImpactsFetchTasBaseline", run_cmd: str = "python -m foo") -> Template:
    app = cdk.App()
    bucket_stack = _BucketHarness(app, "TestBucketHarness")
    stack = PipelineStepBuildProjectStack(
        app,
        "TestPipelineStepBuildProjectStack",
        project_name=project_name,
        run_cmd=run_cmd,
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
    """Manually triggered only — see ADR-006 Step 7. A webhook here would mean re-fetching on
    every push to main, which this pipeline's own update cadence doesn't call for."""
    resources = _template().to_json()["Resources"]
    assert not any(r["Type"] == "AWS::CodeBuild::ProjectWebhook" for r in resources.values())


def test_project_has_the_given_name():
    _template(project_name="ClimateImpactsFetchTasBaseline").has_resource_properties(
        "AWS::CodeBuild::Project",
        {"Name": "ClimateImpactsFetchTasBaseline"},
    )


def test_run_cmd_is_baked_in_as_a_fixed_environment_variable():
    """The whole point: no override needed at invocation time, so nothing can pass a different
    command to this project than the one it was created for."""
    _template(run_cmd="python -m climate_pipeline.fetch.climate --variable tas --window baseline").has_resource_properties(
        "AWS::CodeBuild::Project",
        {
            "Environment": Match.object_like(
                {
                    "EnvironmentVariables": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "Name": "RUN_CMD",
                                    "Value": "python -m climate_pipeline.fetch.climate --variable tas --window baseline",
                                }
                            )
                        ]
                    )
                }
            )
        },
    )


def test_two_instances_produce_two_independent_projects():
    """The actual guarantee this construct exists to give: two steps never share one project."""
    app = cdk.App()
    bucket_stack = _BucketHarness(app, "TestBucketHarness2")
    stack_a = PipelineStepBuildProjectStack(
        app,
        "StackA",
        project_name="ClimateImpactsFetchTasBaseline",
        run_cmd="python -m a",
        bucket=bucket_stack.bucket,
        github_owner="example-owner",
        github_repo="example-repo",
    )
    stack_b = PipelineStepBuildProjectStack(
        app,
        "StackB",
        project_name="ClimateImpactsFetchTasFuture",
        run_cmd="python -m b",
        bucket=bucket_stack.bucket,
        github_owner="example-owner",
        github_repo="example-repo",
    )
    names_a = {r["Properties"]["Name"] for r in Template.from_stack(stack_a).to_json()["Resources"].values() if r["Type"] == "AWS::CodeBuild::Project"}
    names_b = {r["Properties"]["Name"] for r in Template.from_stack(stack_b).to_json()["Resources"].values() if r["Type"] == "AWS::CodeBuild::Project"}
    assert names_a == {"ClimateImpactsFetchTasBaseline"}
    assert names_b == {"ClimateImpactsFetchTasFuture"}


def test_compute_is_upgraded_past_the_low_throughput_default():
    _template().has_resource_properties(
        "AWS::CodeBuild::Project",
        {"Environment": Match.object_like({"ComputeType": "BUILD_GENERAL1_MEDIUM"})},
    )


def test_timeout_is_generous_past_the_untested_default():
    _template().has_resource_properties(
        "AWS::CodeBuild::Project",
        {"TimeoutInMinutes": 240},
    )
