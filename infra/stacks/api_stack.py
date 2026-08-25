from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
)
from constructs import Construct


class ApiStack(Stack):
    """The real orchestration/API tier — Lambda, per ADR-005's resolved compute-topology decision
    (this tier has nothing persistent to amortize, unlike understanding()/narration() on
    ECS/Fargate — see ModelServicesStack). Two functions, one shared container image (climate_
    pipeline's dependencies are heavy enough to need a container image, not a ZIP package), each
    pointed at a different handler within it via CMD override — not two separate image builds for
    what's the same real dependency set.

    Deliberately NOT deployed as part of tonight's work — same reasoning as ModelServicesStack.
    UNDERSTANDING_URL/NARRATION_URL point at those services' ALBs once ModelServicesStack is
    actually deployed; wired here as constructor args so this stack never hardcodes them.
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

        # cmd (the handler override) is a real parameter of DockerImageCode.from_image_asset, not
        # of DockerImageFunction itself (confirmed live against the installed CDK version) — one
        # from_image_asset call per handler, same directory/Dockerfile, CDK content-addresses the
        # underlying image build so this doesn't mean building the image twice.
        interpret_image_code = lambda_.DockerImageCode.from_image_asset(
            directory="..", file="api/Dockerfile", cmd=["lambda_handler.interpret_lambda_handler"]
        )
        narrate_image_code = lambda_.DockerImageCode.from_image_asset(
            directory="..", file="api/Dockerfile", cmd=["lambda_handler.narrate_lambda_handler"]
        )

        execution_role = iam.Role(self, "ApiLambdaRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        execution_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )
        isimip_data_bucket.grant_read(execution_role)

        common_env = {
            "ISIMIP_BUCKET": isimip_data_bucket.bucket_name,
            "UNDERSTANDING_URL": understanding_url,
            "NARRATION_URL": narration_url,
        }

        interpret_fn = lambda_.DockerImageFunction(
            self,
            "InterpretFunction",
            code=interpret_image_code,
            role=execution_role,
            timeout=Duration.seconds(30),
            memory_size=1024,
            environment=common_env,
        )

        narrate_fn = lambda_.DockerImageFunction(
            self,
            "NarrateFunction",
            code=narrate_image_code,
            role=execution_role,
            # Narrate does real LLM generation + verification, real retries — a longer timeout
            # than interpret's cheap precomputed-grid lookups.
            timeout=Duration.seconds(60),
            memory_size=1024,
            environment=common_env,
        )

        api = apigateway.RestApi(self, "ClimateImpactsApi", rest_api_name="ClimateImpactsApi")
        api.root.add_resource("interpret").add_method("POST", apigateway.LambdaIntegration(interpret_fn))
        api.root.add_resource("narrate").add_method("POST", apigateway.LambdaIntegration(narrate_fn))

        CfnOutput(self, "ApiUrl", value=api.url)
