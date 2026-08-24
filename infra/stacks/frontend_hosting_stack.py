from aws_cdk import (
    CfnOutput,
    Stack,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3 as s3,
)
from constructs import Construct

# Rewrites a request for a path with no file extension to /index.html, so a
# direct visit, refresh, or shared link to a client-side route (e.g.
# /occitanie/maize/2C) doesn't 404 against the S3 origin. See ADR-001.
_SPA_FALLBACK_FUNCTION_CODE = """
function handler(event) {
    var request = event.request;
    if (!request.uri.includes(".")) {
        request.uri = "/index.html";
    }
    return request;
}
"""

# Security headers for a public, security-scanned NASA-branded site. See
# ADR-001. Deliberately conservative; loosen only for a specific, named
# requirement (e.g. an embedded map tile provider needing a wider CSP).
_SECURITY_HEADERS_FUNCTION_CODE = """
function handler(event) {
    var response = event.response;
    var headers = response.headers;
    headers["strict-transport-security"] = { value: "max-age=63072000; includeSubDomains; preload" };
    headers["x-content-type-options"] = { value: "nosniff" };
    headers["x-frame-options"] = { value: "DENY" };
    headers["referrer-policy"] = { value: "strict-origin-when-cross-origin" };
    headers["content-security-policy"] = { value: "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; connect-src 'self'" };
    return response;
}
"""


class FrontendHostingStack(Stack):
    """S3 + CloudFront static hosting for the frontend, per ADR-001.

    Deliberately does not configure a custom domain/certificate: this is a
    portfolio project with no NASA domain to point at, so a self-issued
    placeholder would misrepresent that as settled. The WAF web ACL is
    wired in via web_acl_arn (see FrontendWafStack, app.py).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        web_acl_arn: str,
        processed_data_bucket: s3.IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self,
            "FrontendBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # Required by CloudFront origin access control.
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
        )

        spa_fallback_function = cloudfront.Function(
            self,
            "SpaFallbackFunction",
            code=cloudfront.FunctionCode.from_inline(_SPA_FALLBACK_FUNCTION_CODE),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        security_headers_function = cloudfront.Function(
            self,
            "SecurityHeadersFunction",
            code=cloudfront.FunctionCode.from_inline(_SECURITY_HEADERS_FUNCTION_CODE),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
        )

        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            default_root_object="index.html",
            web_acl_id=web_acl_arn,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=spa_fallback_function,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    ),
                    cloudfront.FunctionAssociation(
                        function=security_headers_function,
                        event_type=cloudfront.FunctionEventType.VIEWER_RESPONSE,
                    ),
                ],
            ),
        )

        # Precomputed region data (process stage output, see ADR-006/pipeline/README.md) served
        # as a second origin on this same distribution, path-scoped — exactly the pattern ADR-004
        # Step 3 names for tile data ("a separate bucket... added as a second origin... via a
        # path pattern e.g. /tiles/*"). Scoped to /precomputed/* only: the isimip data bucket
        # also holds raw/ and _profiling/ prefixes that must stay unreachable through CloudFront,
        # and a path pattern with no matching behavior for those prefixes is what keeps them out
        # — the OAC grant itself is bucket-wide, same as CDK gives the frontend bucket above.
        #
        # processed_data_bucket lives in a *different* stack (IsimipDataBucketStack) than this
        # distribution. Passing the real construct straight into with_origin_access_control()
        # here would make CDK try to attach a bucket policy statement (in the bucket's own stack)
        # conditioned on this distribution's ARN — but this distribution's own origin needs the
        # bucket's domain name first, so that's a genuine CloudFormation dependency cycle between
        # the two stacks, not just a test-harness artifact (confirmed via a failing `cdk synth`).
        # Importing the bucket by name breaks the cycle: CDK can't auto-manage policy on an
        # imported reference, so the read grant is instead added explicitly in
        # IsimipDataBucketStack itself, scoped to any CloudFront distribution in this account
        # (not this distribution's exact ARN) — see that stack for the actual policy statement.
        imported_processed_data_bucket = s3.Bucket.from_bucket_name(
            self, "ImportedProcessedDataBucket", processed_data_bucket.bucket_name
        )
        distribution.add_behavior(
            "/precomputed/*",
            origins.S3BucketOrigin.with_origin_access_control(imported_processed_data_bucket),
            viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
        )

        self.bucket = bucket
        self.distribution = distribution

        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        CfnOutput(
            self,
            "DistributionDomainName",
            value=distribution.distribution_domain_name,
        )
