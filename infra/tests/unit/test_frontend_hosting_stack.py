import aws_cdk as cdk
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


def _template() -> Template:
    app = cdk.App()
    bucket_stack = _BucketHarness(app, "TestBucketHarness")
    stack = FrontendHostingStack(
        app,
        "TestFrontendHostingStack",
        web_acl_arn=_TEST_WEB_ACL_ARN,
        processed_data_bucket=bucket_stack.bucket,
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
