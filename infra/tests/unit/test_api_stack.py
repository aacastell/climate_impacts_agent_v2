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


def test_functions_share_one_built_image_but_override_the_handler_per_function():
    # Confirmed live against the real synthesized template: cmd on DockerImageCode.from_image_asset
    # does NOT change the built image (both functions share one image asset — efficient, no
    # duplicate build) — it's injected as each function's own ImageConfig.Command override
    # instead. Real regression guard that interpret/narrate actually run different handlers, not
    # a guess about how the two mechanisms compose.
    import json as _json

    resources = _template().to_json()["Resources"]
    fns = [r for r in resources.values() if r["Type"] == "AWS::Lambda::Function"]
    image_uris = {_json.dumps(fn["Properties"]["Code"]["ImageUri"], sort_keys=True) for fn in fns}
    assert len(image_uris) == 1

    commands = {tuple(fn["Properties"]["ImageConfig"]["Command"]) for fn in fns}
    assert commands == {("lambda_handler.interpret_lambda_handler",), ("lambda_handler.narrate_lambda_handler",)}


def test_creates_a_rest_api_with_both_routes():
    template = _template()
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)
    resources = template.to_json()["Resources"]
    paths = {r["Properties"]["PathPart"] for r in resources.values() if r["Type"] == "AWS::ApiGateway::Resource"}
    assert paths == {"interpret", "narrate"}
