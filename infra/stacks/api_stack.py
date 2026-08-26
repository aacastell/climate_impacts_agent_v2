from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigateway as apigateway,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
)
from constructs import Construct


class ApiStack(Stack):
    """The real orchestration/API tier — Lambda, per ADR-005's resolved compute-topology decision
    (this tier has nothing persistent to amortize, unlike understanding()/narration() on
    ECS/Fargate — see ModelServicesStack). Two functions, two separate container images (not one
    shared image with a CMD override, as this stack used to do) — a real, deliberate split: since
    ADR-004's actual decision was restored (interpret() returns identifiers only, never touches
    the precomputed store), interpret()'s image genuinely no longer needs climate_pipeline's
    xarray/netCDF4/numpy dependency at all, confirmed live (its handler imports in ~114ms with
    only boto3+httpx installed) — a shared image with narrate() (which still needs those for its
    own real server-side verification-gate lookups) would mean interpret()'s cold start kept
    paying for weight it never uses. Each function also gets its own least-privilege role now for
    the same reason — interpret() has no S3 access to grant anymore.

    UNDERSTANDING_URL/NARRATION_URL point at those services' ALBs once ModelServicesStack is
    actually deployed; wired here as constructor args so this stack never hardcodes them.

    self.api is exposed so FrontendHostingStack can add it as a CloudFront origin behind /api/*
    on the same distribution the frontend is served from (see that stack) — same-origin per
    ADR-001, no CORS needed.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        isimip_data_bucket: s3.IBucket,
        understanding_url: str,
        narration_url: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Two real, separate image builds now — see this class's own docstring for why a shared
        # image + CMD override (this stack's previous design) stopped making sense once
        # interpret() genuinely dropped its climate_pipeline data dependency.
        interpret_image_code = lambda_.DockerImageCode.from_image_asset(directory="..", file="api/Dockerfile")
        narrate_image_code = lambda_.DockerImageCode.from_image_asset(directory="..", file="api/Dockerfile.narrate")

        # ADR-005's "workflow is stateful, compute layer stays stateless" design for clarify()
        # round-trips: a request needing clarification gets a query_id, its partial resolution
        # state (understanding()'s trace, see orchestrator.py) is written here, and a follow-up
        # request carrying query_id + the user's answer resumes it. PAY_PER_REQUEST, not
        # provisioned — no fixed floor cost at rest, unlike the Redis candidate ADR-005 named but
        # never committed to (see the ADR's own Revisit triggers). Session data, not durable
        # business data — DESTROY is correct here, unlike the data buckets elsewhere in this
        # project that are explicitly RETAIN.
        session_table = dynamodb.Table(
            self,
            "ClarifySessionTable",
            partition_key=dynamodb.Attribute(name="query_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="expires_at",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Least privilege, one role per real access pattern — interpret() never touches S3
        # anymore, so it never gets that grant; narrate() never touches the session table.
        interpret_role = iam.Role(self, "InterpretLambdaRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        interpret_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )
        session_table.grant_read_write_data(interpret_role)

        narrate_role = iam.Role(self, "NarrateLambdaRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        narrate_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )
        isimip_data_bucket.grant_read(narrate_role)

        # Real bug caught live in ModelServicesStack before it could repeat here: cdk deploy
        # builds these Docker images locally, and on an Apple Silicon Mac that's ARM64 — Lambda
        # defaults to x86_64, which would fail with "exec format error" at invocation despite the
        # deploy itself reporting success. Matching Lambda's architecture to what's actually
        # built avoids a second, harder-to-catch instance of the same class of bug.
        _ARCHITECTURE = lambda_.Architecture.ARM_64

        interpret_fn = lambda_.DockerImageFunction(
            self,
            "InterpretFunction",
            code=interpret_image_code,
            role=interpret_role,
            timeout=Duration.seconds(30),
            memory_size=1024,
            environment={
                "UNDERSTANDING_URL": understanding_url,
                "SESSION_TABLE_NAME": session_table.table_name,
            },
            architecture=_ARCHITECTURE,
        )

        narrate_fn = lambda_.DockerImageFunction(
            self,
            "NarrateFunction",
            code=narrate_image_code,
            role=narrate_role,
            # Narrate does real LLM generation + verification, real retries — a longer timeout
            # than interpret's cheap identifier resolution.
            timeout=Duration.seconds(60),
            memory_size=1024,
            environment={
                "ISIMIP_BUCKET": isimip_data_bucket.bucket_name,
                "NARRATION_URL": narration_url,
            },
            architecture=_ARCHITECTURE,
        )

        api = apigateway.RestApi(self, "ClimateImpactsApi", rest_api_name="ClimateImpactsApi")
        # Routes nested under /api so they land at the exact same path CloudFront forwards them
        # at — see FrontendHostingStack's /api/* behavior. CloudFront forwards the literal
        # request path (it doesn't strip the /api prefix its path pattern matched on), so the
        # real deployed API Gateway resource has to be /api/interpret, not /interpret, for the
        # two to actually line up.
        api_resource = api.root.add_resource("api")
        api_resource.add_resource("interpret").add_method("POST", apigateway.LambdaIntegration(interpret_fn))
        api_resource.add_resource("narrate").add_method("POST", apigateway.LambdaIntegration(narrate_fn))

        self.api = api

        CfnOutput(self, "ApiUrl", value=api.url)
