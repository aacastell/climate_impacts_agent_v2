import aws_cdk as cdk
from aws_cdk import aws_apigateway as apigateway
from aws_cdk import aws_s3 as s3
from aws_cdk.assertions import Match, Template
from constructs import Construct

from stacks.frontend_hosting_stack import FrontendHostingStack


_TEST_WEB_ACL_ARN = (
    "arn:aws:wafv2:us-east-1:123456789012:global/webacl/test/"
    "00000000-0000-0000-0000-000000000000"
)


class _BucketHarness(cdk.Stack):
    """A bucket to stand in for IsimipDataBucketStack's bucket, the way
    FrontendHostingStack is actually wired in app.py."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.bucket = s3.Bucket(self, "TestProcessedDataBucket")


class _ApiHarness(cdk.Stack):
    """A minimal RestApi to stand in for ApiStack's real one, the way
    FrontendHostingStack is actually wired in app.py."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.api = apigateway.RestApi(self, "TestApi")
        self.api.root.add_method("GET")


def _template() -> Template:
    app = cdk.App()
    bucket_stack = _BucketHarness(app, "TestBucketHarness")
    api_stack = _ApiHarness(app, "TestApiHarness")
    stack = FrontendHostingStack(
        app,
        "TestFrontendHostingStack",
        web_acl_arn=_TEST_WEB_ACL_ARN,
        processed_data_bucket=bucket_stack.bucket,
        api=api_stack.api,
    )
    return Template.from_stack(stack)


def test_bucket_blocks_public_access():
    _template().has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )


def test_distribution_has_two_cloudfront_functions():
    _template().resource_count_is("AWS::CloudFront::Function", 2)


def test_csp_allows_webassembly_compilation():
    # Real bug caught live in production, not a preemptive loosening: h5wasm (the real
    # client-side HDF5/NetCDF4 parser ADR-004's restored decision depends on — see
    # frontend/src/precomputedFetch.ts) failed outright with a real CSP violation the moment it
    # was deployed ("WebAssembly.instantiate(): ... 'unsafe-eval' is not an allowed source"),
    # because Vite's local dev server never enforces this header. 'wasm-unsafe-eval' specifically
    # — not the broader 'unsafe-eval', which would also permit eval()/Function() for plain JS.
    resources = _template().to_json()["Resources"]
    functions = [r for r in resources.values() if r["Type"] == "AWS::CloudFront::Function"]
    security_headers_fn = next(f for f in functions if "wasm-unsafe-eval" in f["Properties"]["FunctionCode"])
    assert "'unsafe-eval'" not in security_headers_fn["Properties"]["FunctionCode"].replace("'wasm-unsafe-eval'", "")


def test_distribution_has_an_api_path_behavior():
    """A third origin/behavior for /api/* — the API tier (ApiStack), same distribution as the
    frontend per ADR-001, so the browser never makes a cross-origin call."""
    _template().has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "CacheBehaviors": Match.array_with(
                        [Match.object_like({"PathPattern": "/api/*"})]
                    )
                }
            )
        },
    )


def test_distribution_has_a_processed_path_behavior():
    """A second origin/behavior for /processed/* — see ADR-004 Step 3's
    anticipated pattern, applied here to process-stage output instead of
    map tiles. Matches the actual S3 key prefix process_global writes to
    (processed/global/...), not an earlier /precomputed/* that never
    matched any real key."""
    _template().has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "CacheBehaviors": Match.array_with(
                        [Match.object_like({"PathPattern": "/processed/*"})]
                    )
                }
            )
        },
    )
