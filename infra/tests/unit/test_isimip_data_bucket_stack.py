import aws_cdk as cdk
from aws_cdk.assertions import Template

from stacks.isimip_data_bucket_stack import IsimipDataBucketStack


def _template() -> Template:
    app = cdk.App()
    stack = IsimipDataBucketStack(
        app, "TestIsimipDataBucketStack", env=cdk.Environment(account="123456789012", region="us-east-2")
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


def test_bucket_name_is_fixed_and_account_scoped():
    _template().has_resource_properties(
        "AWS::S3::Bucket",
        {"BucketName": "climate-impacts-isimip-raw-123456789012"},
    )


def test_bucket_is_retained_on_stack_deletion():
    template = _template().to_json()
    [bucket] = [
        resource for resource in template["Resources"].values() if resource["Type"] == "AWS::S3::Bucket"
    ]
    assert bucket["DeletionPolicy"] == "Retain"


def test_no_lifecycle_rule_is_set():
    """Storage-class transition is the process stage's own event-driven
    action once it exists (see ADR-006) — not a bucket-level default that
    could strand a run mid-flight on a premature archival."""
    _template().to_json()  # sanity: template renders
    resources = _template().to_json()["Resources"]
    [bucket] = [r for r in resources.values() if r["Type"] == "AWS::S3::Bucket"]
    assert "LifecycleConfiguration" not in bucket["Properties"]
