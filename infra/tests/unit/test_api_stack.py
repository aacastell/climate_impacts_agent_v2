import aws_cdk as cdk
from aws_cdk import aws_s3 as s3
from aws_cdk.assertions import Match, Template
from constructs import Construct

from stacks.api_stack import ApiStack


class _BucketHarness(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.bucket = s3.Bucket(self, "TestBucket")


def _template() -> Template:
    app = cdk.App()
    bucket_stack = _BucketHarness(app, "TestBucketHarness")
    stack = ApiStack(
        app,
        "TestApiStack",
        isimip_data_bucket=bucket_stack.bucket,
        understanding_url="http://understanding.internal",
        narration_url="http://narration.internal",
    )
    return Template.from_stack(stack)


def test_creates_two_lambda_functions():
    _template().resource_count_is("AWS::Lambda::Function", 2)


def test_both_functions_run_on_arm64_matching_the_locally_built_image():
    # Same real bug class as ModelServicesStack, caught proactively here before it could repeat:
    # cdk deploy builds these images locally (ARM64 on an Apple Silicon Mac); Lambda defaults to
    # x86_64, which would fail with "exec format error" at invocation despite a clean deploy.
    resources = _template().to_json()["Resources"]
    fns = [r for r in resources.values() if r["Type"] == "AWS::Lambda::Function"]
    assert len(fns) == 2
    for fn in fns:
        assert fn["Properties"]["Architectures"] == ["arm64"]


def test_functions_are_two_real_separate_images_not_one_shared_image():
    # Real, deliberate change from this stack's earlier design (one shared image + a CMD
    # override per function): interpret() dropped its climate_pipeline data dependency entirely
    # (ADR-004's restored decision — it returns identifiers only), so its image no longer needs
    # xarray/netCDF4/numpy at all — confirmed live, its handler imports in ~114ms with only
    # boto3+httpx installed. A shared image would mean interpret()'s cold start still paid for
    # narrate()'s real, separate dependency (narrate() still does real server-side lookups for
    # its verification gate). Two distinct Dockerfiles now (api/Dockerfile,
    # api/Dockerfile.narrate) means two distinct built images — this is the real regression guard
    # that they didn't quietly end up sharing one again.
    import json as _json

    resources = _template().to_json()["Resources"]
    fns = [r for r in resources.values() if r["Type"] == "AWS::Lambda::Function"]
    image_uris = {_json.dumps(fn["Properties"]["Code"]["ImageUri"], sort_keys=True) for fn in fns}
    assert len(image_uris) == 2

    # No CMD override needed anymore — each Dockerfile bakes in its own real handler.
    for fn in fns:
        assert "ImageConfig" not in fn["Properties"]


def test_creates_a_rest_api_with_both_routes_nested_under_api():
    # Nested under /api, not at the root — see ApiStack's own comment: this has to match the
    # literal path CloudFront's /api/* behavior forwards (FrontendHostingStack), which does not
    # strip the /api prefix.
    template = _template()
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)
    resources = template.to_json()["Resources"]
    paths = {r["Properties"]["PathPart"] for r in resources.values() if r["Type"] == "AWS::ApiGateway::Resource"}
    assert paths == {"api", "interpret", "narrate"}


def test_session_table_has_ttl_and_pay_per_request_billing():
    # ADR-005's clarify()/query_id design: pay-per-request (no fixed floor cost, unlike the
    # Redis candidate ADR-005 named but never committed to) and a TTL attribute so expired
    # sessions clear themselves without a cleanup job.
    template = _template()
    template.resource_count_is("AWS::DynamoDB::Table", 1)
    template.has_resource_properties(
        "AWS::DynamoDB::Table",
        Match.object_like(
            {
                "BillingMode": "PAY_PER_REQUEST",
                "TimeToLiveSpecification": {"AttributeName": "expires_at", "Enabled": True},
            }
        ),
    )


def test_lambda_role_can_access_the_session_table():
    template = _template()
    template.has_resource_properties(
        "AWS::IAM::Policy",
        Match.object_like(
            {
                "PolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [Match.object_like({"Action": Match.array_with(["dynamodb:GetItem"])})]
                        )
                    }
                )
            }
        ),
    )
