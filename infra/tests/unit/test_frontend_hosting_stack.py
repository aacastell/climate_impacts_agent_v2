import aws_cdk as cdk
from aws_cdk.assertions import Template

from stacks.frontend_hosting_stack import FrontendHostingStack


_TEST_WEB_ACL_ARN = (
    "arn:aws:wafv2:us-east-1:123456789012:global/webacl/test/"
    "00000000-0000-0000-0000-000000000000"
)


def _template() -> Template:
    app = cdk.App()
    stack = FrontendHostingStack(
        app, "TestFrontendHostingStack", web_acl_arn=_TEST_WEB_ACL_ARN
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
