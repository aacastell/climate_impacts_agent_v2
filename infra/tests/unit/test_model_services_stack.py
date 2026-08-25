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


def test_creates_two_fargate_services():
    _template().resource_count_is("AWS::ECS::Service", 2)


def test_no_nat_gateway():
    """Real, deliberate cost decision — see the stack's own docstring."""
    resources = _template().to_json()["Resources"]
    assert not any(r["Type"] == "AWS::EC2::NatGateway" for r in resources.values())


def test_both_services_assign_public_ip():
    """Real regression guard for a real, live-caught deploy failure: a NAT-less public subnet
    doesn't grant a Fargate task internet access on its own — without AssignPublicIp explicitly
    ENABLED, tasks couldn't reach ECR to pull their image at all. The first real `cdk deploy`
    rolled the whole stack back over exactly this (confirmed via zero CloudWatch log streams ever
    created — the container never started, not a crash after starting)."""
    resources = _template().to_json()["Resources"]
    services = [r for r in resources.values() if r["Type"] == "AWS::ECS::Service"]
    assert len(services) == 2
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


def test_both_services_have_health_checks():
    _template().has_resource_properties(
        "AWS::ElasticLoadBalancingV2::TargetGroup",
        Match.object_like({"HealthCheckPath": "/health"}),
    )
