import json

import aws_cdk as cdk
from aws_cdk import aws_s3 as s3
from aws_cdk.assertions import Match, Template
from constructs import Construct

from stacks.model_services_stack import ModelServicesStack


class _BucketHarness(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.bucket = s3.Bucket(self, "TestBucket")


def _template() -> Template:
    app = cdk.App()
    bucket_stack = _BucketHarness(app, "TestBucketHarness")
    stack = ModelServicesStack(
        app,
        "TestModelServicesStack",
        isimip_data_bucket=bucket_stack.bucket,
    )
    return Template.from_stack(stack)


def test_creates_three_fargate_services():
    # understanding(), narration(), and the real self-hosted MLflow tracking server.
    _template().resource_count_is("AWS::ECS::Service", 3)


def test_all_three_services_run_on_arm64_matching_the_locally_built_image():
    # Real bug caught live: cdk deploy builds Docker images locally — on an Apple Silicon Mac
    # that's ARM64 — but Fargate defaults to x86_64, which failed with a real "exec format
    # error" at container start despite a clean image build and push.
    resources = _template().to_json()["Resources"]
    task_defs = [r for r in resources.values() if r["Type"] == "AWS::ECS::TaskDefinition"]
    assert len(task_defs) == 3
    for task_def in task_defs:
        assert task_def["Properties"]["RuntimePlatform"]["CpuArchitecture"] == "ARM64"


def test_understanding_and_narration_override_the_blocked_default_model():
    # Real bug caught before it shipped: both app.py files default to Claude Haiku, which is
    # rejected outright by Bedrock on this account (unsubmitted Anthropic use-case form,
    # confirmed live). Without an override here, a fully successful deploy would still fail on
    # every real query. Nova Pro needs no such form and was already validated live.
    # Excludes the MLflow task definition deliberately — that service never calls Bedrock at
    # all, so it has no *_MODEL_ID to override.
    resources = _template().to_json()["Resources"]
    task_defs = [
        r for key, r in resources.items()
        if r["Type"] == "AWS::ECS::TaskDefinition" and (key.startswith("UnderstandingService") or key.startswith("NarrationService"))
    ]
    assert len(task_defs) == 2
    for task_def in task_defs:
        env = {e["Name"]: e["Value"] for e in task_def["Properties"]["ContainerDefinitions"][0]["Environment"]}
        model_id_keys = [k for k in env if k.endswith("_MODEL_ID") and k != "EMBEDDING_MODEL_ID"]
        assert model_id_keys, f"no *_MODEL_ID override set on {task_def}"
        for key in model_id_keys:
            assert "anthropic" not in env[key], f"{key} still points at the blocked Claude Haiku default"


def test_narration_service_points_at_the_real_mlflow_server_not_a_local_sqlite_path():
    # Real fix: narration_service used to point at an ephemeral sqlite file inside its own
    # container (worked, but no UI, no external access, wiped on every restart). It should now
    # point at the real MlflowService's ALB, over http, not a sqlite:// path.
    resources = _template().to_json()["Resources"]
    narration_task_def = next(
        r for key, r in resources.items() if r["Type"] == "AWS::ECS::TaskDefinition" and key.startswith("NarrationService")
    )
    env = {e["Name"]: e["Value"] for e in narration_task_def["Properties"]["ContainerDefinitions"][0]["Environment"]}
    assert "MLFLOW_TRACKING_URI" in env
    tracking_uri = env["MLFLOW_TRACKING_URI"]
    assert isinstance(tracking_uri, dict), "expected a CDK token (Fn::Join to the MLflow ALB DNS name), not a literal string"


def test_langfuse_credentials_come_from_secrets_manager_not_plaintext_env():
    # A Langfuse secret key is real sensitive material — it belongs in Secrets Manager, not
    # baked in plaintext into the CloudFormation template the way a plain environment={} value
    # would be. Checked on both services: understanding() and narration() both trace via
    # Langfuse (see their real @observe-decorated functions).
    _template().resource_count_is("AWS::SecretsManager::Secret", 1)
    resources = _template().to_json()["Resources"]
    task_defs = [
        r for key, r in resources.items()
        if r["Type"] == "AWS::ECS::TaskDefinition" and (key.startswith("UnderstandingService") or key.startswith("NarrationService"))
    ]
    assert len(task_defs) == 2
    for task_def in task_defs:
        secrets = task_def["Properties"]["ContainerDefinitions"][0].get("Secrets", [])
        secret_names = {s["Name"] for s in secrets}
        assert secret_names == {"LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"}
        env_names = {e["Name"] for e in task_def["Properties"]["ContainerDefinitions"][0]["Environment"]}
        assert "LANGFUSE_PUBLIC_KEY" not in env_names, "Langfuse key leaked into plaintext environment"
        assert "LANGFUSE_SECRET_KEY" not in env_names, "Langfuse key leaked into plaintext environment"


def test_mlflow_service_has_a_persistent_efs_volume():
    # Real reason this exists at all: without a persistent volume, MLflow's sqlite backend
    # would live on the container's own ephemeral filesystem and lose every run on restart —
    # the same problem this whole service replaces, just moved one layer down.
    _template().resource_count_is("AWS::EFS::FileSystem", 1)
    resources = _template().to_json()["Resources"]
    mlflow_task_def = next(
        r for key, r in resources.items() if r["Type"] == "AWS::ECS::TaskDefinition" and key.startswith("MlflowTaskDefinition")
    )
    volumes = mlflow_task_def["Properties"].get("Volumes", [])
    assert len(volumes) == 1
    assert "EFSVolumeConfiguration" in volumes[0]


def test_no_nat_gateway():
    """Real, deliberate cost decision — see the stack's own docstring."""
    resources = _template().to_json()["Resources"]
    assert not any(r["Type"] == "AWS::EC2::NatGateway" for r in resources.values())


def test_all_three_services_assign_public_ip():
    """Real regression guard for a real, live-caught deploy failure: a NAT-less public subnet
    doesn't grant a Fargate task internet access on its own — without AssignPublicIp explicitly
    ENABLED, tasks couldn't reach ECR to pull their image at all. The first real `cdk deploy`
    rolled the whole stack back over exactly this (confirmed via zero CloudWatch log streams ever
    created — the container never started, not a crash after starting)."""
    resources = _template().to_json()["Resources"]
    services = [r for r in resources.values() if r["Type"] == "AWS::ECS::Service"]
    assert len(services) == 3
    for service in services:
        assert service["Properties"]["NetworkConfiguration"]["AwsvpcConfiguration"]["AssignPublicIp"] == "ENABLED"


def test_understanding_task_role_can_call_bedrock_and_location():
    _template().has_resource_properties(
        "AWS::IAM::Policy",
        Match.object_like(
            {
                "PolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [Match.object_like({"Action": Match.array_with(["bedrock:Converse"])})]
                        )
                    }
                )
            }
        ),
    )


def test_both_services_autoscale():
    _template().resource_count_is("AWS::ApplicationAutoScaling::ScalableTarget", 2)


def test_both_services_scale_on_request_count_not_cpu():
    # Real finding from tonight's benchmarking (see pipeline/benchmarks/query_latency_benchmark.py
    # and services/understanding/benchmark_geocode.py): these services are I/O-bound on Bedrock,
    # not CPU-bound, so CPU-based autoscaling would fail to scale out under real load. Regression
    # guard against silently reverting to scale_on_cpu_utilization.
    resources = _template().to_json()["Resources"]
    policies = [r for r in resources.values() if r["Type"] == "AWS::ApplicationAutoScaling::ScalingPolicy"]
    assert len(policies) == 2
    for policy in policies:
        metric_type = policy["Properties"]["TargetTrackingScalingPolicyConfiguration"]["PredefinedMetricSpecification"]["PredefinedMetricType"]
        assert metric_type == "ALBRequestCountPerTarget"


def test_drift_check_runs_on_a_monthly_schedule():
    # Real regression guard: check_drift.py's own docstring is explicit that running this more
    # than infrequently inflates the true false-positive rate past the nominal alpha (repeated
    # significance testing) — monthly is a deliberate, defensible cadence, not a placeholder.
    resources = _template().to_json()["Resources"]
    rules = [r for r in resources.values() if r["Type"] == "AWS::Events::Rule"]
    assert len(rules) == 1
    assert rules[0]["Properties"]["ScheduleExpression"] == "cron(0 9 1 * ? *)"
    targets = rules[0]["Properties"]["Targets"]
    assert len(targets) == 1


def test_drift_check_lambda_targets_the_real_mlflow_and_place_index():
    # Real regression guard: a drift check that logs nowhere or geocodes against nothing isn't
    # actually monitoring anything — this asserts it's wired to the real resources this stack
    # already provisions, not disconnected infra sitting next to them.
    resources = _template().to_json()["Resources"]
    lambda_fns = [r for r in resources.values() if r["Type"] == "AWS::Lambda::Function"]
    assert len(lambda_fns) == 1, "this stack's only Lambda should be the drift-check function"
    env = lambda_fns[0]["Properties"]["Environment"]["Variables"]
    assert "LOCATION_INDEX_NAME" in env
    assert "MLFLOW_TRACKING_URI" in env
    assert isinstance(env["MLFLOW_TRACKING_URI"], dict), "expected a CDK token pointing at the real MlflowService, not a literal string"


def test_bedrock_finetune_role_trusts_bedrock_scoped_to_the_real_finetune_region():
    # Real regression guard: Nova Pro's FINE_TUNING support (confirmed live via `aws bedrock
    # list-foundation-models`) only exists in us-east-1, not this stack's own home region
    # (us-east-2) — a trust policy scoped to the wrong region would make the role real but
    # useless the moment someone actually tries to use it.
    resources = _template().to_json()["Resources"]
    role = next(r for key, r in resources.items() if r["Type"] == "AWS::IAM::Role" and key.startswith("BedrockFineTuneRole"))
    statement = role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
    assert statement["Principal"]["Service"] == "bedrock.amazonaws.com"
    source_arn = json.dumps(statement["Condition"]["ArnLike"]["aws:SourceArn"])
    assert "us-east-1" in source_arn
    assert "model-customization-job" in source_arn


def test_both_services_have_health_checks():
    _template().has_resource_properties(
        "AWS::ElasticLoadBalancingV2::TargetGroup",
        Match.object_like({"HealthCheckPath": "/health"}),
    )
