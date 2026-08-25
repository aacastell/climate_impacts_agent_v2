from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_iam as iam,
    aws_s3 as s3,
)
from constructs import Construct


class IsimipDataBucketStack(Stack):
    """The S3 bucket raw ISIMIP/GGCMI data streams into, and DVC's remote
    for the offline scientific data pipeline — per ADR-006.

    Separate from the frontend bucket deliberately (ADR-004/ADR-006's
    established reasoning, repeated here for the same cause): different
    owner, different deploy cadence, and critically, nowhere near
    upload-frontend.sh's `--delete` sync.

    The bucket name is fixed and predictable, not CDK-generated — same
    reasoning as the frontend build project's fixed name (see
    frontend_build_project_stack.py): `pipeline/dvc.yaml` and
    `pipeline/buildspec.yml` are plain text files with no access to CDK's
    generated names, so DVC's remote config has to reference this bucket by
    a name known ahead of deploy time. If this literal ever changes, it has
    to change in three places: here, dvc.yaml, and buildspec.yml.
    """

    BUCKET_NAME_SUFFIX = "climate-impacts-isimip-raw"

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self,
            "IsimipDataBucket",
            bucket_name=f"{self.BUCKET_NAME_SUFFIX}-{self.account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            # Deliberately no lifecycle rule here — see ADR-006 Accompanying
            # decisions on why a blind time-based transition to cheaper
            # storage would risk stranding a process run mid-flight. Any
            # storage-class transition is the process stage's own explicit,
            # event-driven action once it exists, not a bucket-level default.
            #
            # RETAIN, not the CDK default DESTROY: this bucket holds real
            # fetched data. A stack deletion should never silently take
            # that with it.
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Read access for CloudFront (see FrontendHostingStack's /processed/* behavior,
        # frontend_hosting_stack.py) — granted here, in this bucket's own stack, rather than via
        # CDK's usual automatic OAC-bucket-policy wiring: that wiring needs to reference the
        # distribution's ARN, but the distribution's own origin needs this bucket's domain name
        # first, which is a genuine cross-stack CloudFormation dependency cycle (confirmed via a
        # failing `cdk synth` when this was first tried the automatic way). Scoped to any
        # CloudFront distribution in this account, not this one specific distribution's ARN —
        # broader than the exact-ARN condition OAC would normally set, but still only this
        # account's own CloudFront, not the public internet; only raw/ and _profiling/ are meant
        # to stay unreachable through CloudFront, and those still have no matching behavior at
        # all, so this grant being bucket-wide doesn't expose them.
        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[bucket.arn_for_objects("*")],
                principals=[iam.ServicePrincipal("cloudfront.amazonaws.com")],
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            )
        )

        self.bucket = bucket

        CfnOutput(self, "BucketName", value=bucket.bucket_name)
