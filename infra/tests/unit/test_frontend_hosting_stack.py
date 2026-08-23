import aws_cdk as cdk
from aws_cdk.assertions import Template

from stacks.frontend_hosting_stack import FrontendHostingStack


def _template() -> Template:
    app = cdk.App()
    stack = FrontendHostingStack(app, "TestFrontendHostingStack")
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
