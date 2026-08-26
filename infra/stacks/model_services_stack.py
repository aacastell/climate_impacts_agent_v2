from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    SecretValue,
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_efs as efs,
    aws_iam as iam,
    aws_location as location,
    aws_logs as logs,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class ModelServicesStack(Stack):
    """Real ECS/Fargate infrastructure for understanding() and narration() — ADR-005's resolved
    compute-topology decision: these two get scalable, persistent compute because each holds real
    state worth amortizing across requests (a model client with its own connection/latency
    profile — the fine-tuned model checkpoint once that exists for understanding(); retrieval
    embeddings and the corpus for narration()). The orchestration/API tier does not get this
    treatment (Lambda, see ADR-005) because it has nothing comparable to amortize.

    Real, checked via the CDK Python testing framework (Template.from_stack, no real AWS calls)
    and via `cdk deploy` itself. A first real deploy attempt caught a genuine bug here: Fargate
    tasks in a NAT-less public subnet still need `assign_public_ip=True` explicitly — a public
    subnet alone doesn't grant a task internet access. Without it, tasks couldn't reach ECR to
    even pull their image, the ECS service never stabilized, and CloudFormation rolled the whole
    stack back — confirmed live via zero CloudWatch log streams ever created (the container never
    started) and the stack's own rollback events, not guessed at.

    One real, deliberately unresolved item, flagged rather than hidden: both services get a
    public-but-security-group-scoped Application Load Balancer for now, since neither the
    orchestration Lambda's own network placement (VPC-attached or not) nor the exact
    access-control approach (VPC Link + private ALB vs. SigV4-signed requests vs. something else)
    has been decided. Tightening this to a private path is real follow-up work, not done here.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        isimip_data_bucket: s3.IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Real, checked-live blocker, not the model this project actually wants long-term:
        # Claude Haiku (both services' real default) is rejected outright by Bedrock —
        # "Model use case details have not been submitted for this account" — a separate,
        # still-open Anthropic account form, not something this code can work around. Nova Pro
        # needs no such form and was already validated live (today's real baseline eval, 92%
        # accuracy). Revert to the Claude Haiku default once that form clears — both app.py
        # files already default to it, so removing this override is the entire revert.
        _TEMPORARY_MODEL_ID = "us.amazon.nova-pro-v1:0"

        # Real Secrets Manager secret, not a plain environment variable — a Langfuse secret key
        # belongs here, not baked in plaintext into the CloudFormation template the way a plain
        # `environment={}` value would be. Starts with empty placeholder values: this stack
        # cannot itself sign up for Langfuse Cloud (that's a real third-party account only a
        # human can create) — once real keys exist, populate this with one command:
        #   aws secretsmanager put-secret-value --secret-id <this secret's name/ARN> \
        #     --secret-string '{"public_key": "pk-lf-...", "secret_key": "sk-lf-..."}'
        # then force a new deployment (or just redeploy) so the running tasks pick it up — ECS
        # reads secrets at container start, not continuously.
        langfuse_secret = secretsmanager.Secret(
            self,
            "LangfuseCredentials",
            secret_object_value={
                "public_key": SecretValue.unsafe_plain_text(""),
                "secret_key": SecretValue.unsafe_plain_text(""),
            },
            removal_policy=RemovalPolicy.DESTROY,
        )

        # No NAT gateway — real, ongoing per-hour cost for infra nobody has decided to actually
        # run yet. Public subnets with each Fargate task assigned its own public IP is the
        # standard cost-conscious pattern for outbound-only Fargate workloads (calling Bedrock,
        # S3, Location — never accepting unsolicited inbound except through the ALB/security
        # group). Revisit once there's a reason (e.g. the private-ALB access-control decision
        # above) to want NAT instead.
        vpc = ec2.Vpc(
            self,
            "ModelServicesVpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24)],
        )

        cluster = ecs.Cluster(
            self, "ModelServicesCluster", vpc=vpc, container_insights_v2=ecs.ContainerInsights.ENABLED
        )

        log_group = logs.LogGroup(
            self,
            "ModelServicesLogGroup",
            log_group_name="/climate-impacts/model-services",
            retention=logs.RetentionDays.ONE_MONTH,
            # Real bug hit on a real redeploy: LogGroup defaults to RETAIN, so a rolled-back
            # stack left this orphaned with its explicit name still claimed, and the next
            # deploy attempt failed outright ("already exists") before ever reaching the bug
            # it was retrying to fix. Logs aren't durable business data here — DESTROY is
            # correct, same reasoning as the session table.
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Real, CDK-managed Place Index — replaces the temporary CLI-created "geocode-verification-test"
        # index used for tonight's live testing, which was never provisioned by this stack and no
        # longer exists. Esri, no storage (this agent never persists results), same data source
        # already validated live against real ambiguous-region queries.
        geocode_index = location.CfnPlaceIndex(
            self,
            "GeocodeIndex",
            data_source="Esri",
            index_name="climate-impacts-geocode",
            pricing_plan="RequestBasedUsage",
        )

        understanding_task_role = iam.Role(
            self, "UnderstandingTaskRole", assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com")
        )
        understanding_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:Converse", "bedrock:ConverseStream"],
                resources=["*"],  # Bedrock model/inference-profile ARNs, scoped tighter once the real model choice is locked
            )
        )
        understanding_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["geo:SearchPlaceIndexForText"],
                resources=[
                    f"arn:aws:geo:{self.region}:{self.account}:place-index/{geocode_index.index_name}"
                ],
            )
        )
        isimip_data_bucket.grant_read(understanding_task_role)
        langfuse_secret.grant_read(understanding_task_role)

        self.understanding_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "UnderstandingService",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=1,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(
                    directory="..",
                    file="services/understanding/Dockerfile",
                ),
                container_port=8000,
                task_role=understanding_task_role,
                log_driver=ecs.LogDrivers.aws_logs(stream_prefix="understanding", log_group=log_group),
                environment={
                    "ISIMIP_BUCKET": isimip_data_bucket.bucket_name,
                    "LOCATION_INDEX_NAME": geocode_index.index_name,
                    "UNDERSTANDING_MODEL_ID": _TEMPORARY_MODEL_ID,
                },
                # Real Langfuse wiring, not yet real Langfuse tracing — the langfuse Python SDK
                # already reads these two env var names on its own (see services/understanding/
                # orchestrator.py's @observe decorators, already written against this exact
                # contract). Empty values today (see langfuse_secret above) mean the client
                # silently no-ops, same as it's done all along — the moment real keys are in the
                # secret and this redeploys, tracing goes live with zero code changes.
                secrets={
                    "LANGFUSE_PUBLIC_KEY": ecs.Secret.from_secrets_manager(langfuse_secret, "public_key"),
                    "LANGFUSE_SECRET_KEY": ecs.Secret.from_secrets_manager(langfuse_secret, "secret_key"),
                },
            ),
            public_load_balancer=True,
            listener_port=80,
            assign_public_ip=True,
            # A real lesson from today's own failed deploy: without this, a task that can't
            # start (like the assign_public_ip bug above) doesn't fail fast — CDK's own
            # synth-time warning states plainly that CloudFormation can take up to 3 hours to
            # give up without it. rollback=True actually rolls the stack back automatically
            # once the circuit breaker trips, instead of just stopping and leaving it broken.
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
            # Real bug caught live: cdk deploy builds Docker images locally, and on an
            # Apple Silicon Mac that means ARM64 images — but Fargate defaults to x86_64,
            # so the container failed with "exec format error" the moment it tried to run
            # uvicorn, even though the image built and pushed successfully. Matching Fargate's
            # runtime to what's actually built avoids this, and ARM64 (Graviton) Fargate is
            # also genuinely ~20% cheaper per vCPU-hour than x86.
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        self.understanding_service.target_group.configure_health_check(path="/health")
        understanding_scaling = self.understanding_service.service.auto_scale_task_count(min_capacity=1, max_capacity=4)
        # Request-count-based, not CPU-based — real finding from tonight's benchmarking (see
        # pipeline/benchmarks/query_latency_benchmark.py and services/understanding/
        # benchmark_geocode.py): this service's per-request work is dominated by waiting on
        # Bedrock (network I/O), not local computation. CPU utilization stays low under real
        # concurrent load precisely because the process is idle-waiting, not computing — CPU-based
        # scaling would fail to scale out exactly when it needs to. requests_per_target=20 is a
        # conservative starting point (roughly half FastAPI/Starlette's default ~40-thread
        # threadpool, leaving headroom), not a measured number — Bedrock's own real per-call
        # latency is still unmeasured tonight (account-wide Bedrock quota is 0, confirmed via
        # aws service-quotas), so this needs recalibration once that's fixed and real load data
        # exists.
        understanding_scaling.scale_on_request_count(
            "UnderstandingRequestScaling",
            requests_per_target=20,
            target_group=self.understanding_service.target_group,
            scale_in_cooldown=Duration.seconds(60),
            scale_out_cooldown=Duration.seconds(30),
        )

        # A real, self-hosted MLflow tracking server — not the ephemeral sqlite-inside-the-
        # narration-container backend that predates this. Real reason this exists: that backend
        # genuinely worked (mlflow.start_run() succeeded, no crash) but had no UI, no external
        # access, and was wiped on every task restart or redeploy — "wired up" in the sense of
        # not crashing, not in the sense of being something anyone could actually look at.
        # EFS, not RDS: a real persistent volume for the sqlite database at a fraction of RDS's
        # fixed monthly floor (pay-per-GB-used, no minimum instance cost) — the same
        # no-fixed-cost-without-demonstrated-need reasoning already applied elsewhere in this
        # project (ADR-008, the session table's DynamoDB-over-Redis choice).
        mlflow_efs = efs.FileSystem(
            self,
            "MlflowFileSystem",
            vpc=vpc,
            removal_policy=RemovalPolicy.DESTROY,  # tracking data, not durable business data
        )

        mlflow_task_role = iam.Role(
            self, "MlflowTaskRole", assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com")
        )
        # Artifacts (eval_capture.py's log_dict payloads) live under a prefix in the existing
        # data bucket rather than a second bucket — no new resource for something this small.
        isimip_data_bucket.grant_read_write(mlflow_task_role, "mlflow-artifacts/*")

        mlflow_task_definition = ecs.FargateTaskDefinition(
            self,
            "MlflowTaskDefinition",
            cpu=512,
            memory_limit_mib=1024,
            task_role=mlflow_task_role,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        mlflow_task_definition.add_volume(
            name="mlflow-data",
            efs_volume_configuration=ecs.EfsVolumeConfiguration(file_system_id=mlflow_efs.file_system_id),
        )
        mlflow_container = mlflow_task_definition.add_container(
            "MlflowContainer",
            image=ecs.ContainerImage.from_asset(directory="..", file="services/mlflow/Dockerfile"),
            port_mappings=[ecs.PortMapping(container_port=5000)],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="mlflow", log_group=log_group),
            environment={"MLFLOW_ARTIFACT_ROOT": f"s3://{isimip_data_bucket.bucket_name}/mlflow-artifacts"},
        )
        mlflow_container.add_mount_points(
            ecs.MountPoint(container_path="/mlflow-data", source_volume="mlflow-data", read_only=False)
        )

        self.mlflow_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "MlflowService",
            cluster=cluster,
            task_definition=mlflow_task_definition,
            desired_count=1,
            public_load_balancer=True,
            listener_port=80,
            assign_public_ip=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
        )
        self.mlflow_service.target_group.configure_health_check(path="/health")
        # The real cross-construct wiring EFS needs: its own security group must allow inbound
        # NFS (2049) from whatever's mounting it — created after the service exists so there's a
        # real security group to reference, not a chicken-and-egg problem despite the read order.
        mlflow_efs.connections.allow_default_port_from(self.mlflow_service.service)

        narration_task_role = iam.Role(
            self, "NarrationTaskRole", assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com")
        )
        narration_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:Converse", "bedrock:ConverseStream"],
                resources=["*"],
            )
        )
        langfuse_secret.grant_read(narration_task_role)

        self.narration_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "NarrationService",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=1,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(
                    directory="..",
                    file="services/narration/Dockerfile",
                ),
                container_port=8000,
                task_role=narration_task_role,
                log_driver=ecs.LogDrivers.aws_logs(stream_prefix="narration", log_group=log_group),
                environment={
                    "NARRATION_MODEL_ID": _TEMPORARY_MODEL_ID,
                    # Points at the real, self-hosted MLflow server above (MlflowService) — an
                    # http:// tracking URI, not a local sqlite path. mlflow's client library
                    # talks to a real tracking server over its REST API when given one, same
                    # mlflow.start_run()/log_metric() calls in eval_capture.py, no code change
                    # needed there for this to go from "doesn't crash" to "actually visible."
                    "MLFLOW_TRACKING_URI": f"http://{self.mlflow_service.load_balancer.load_balancer_dns_name}",
                },
                secrets={
                    "LANGFUSE_PUBLIC_KEY": ecs.Secret.from_secrets_manager(langfuse_secret, "public_key"),
                    "LANGFUSE_SECRET_KEY": ecs.Secret.from_secrets_manager(langfuse_secret, "secret_key"),
                },
            ),
            public_load_balancer=True,
            listener_port=80,
            assign_public_ip=True,
            # A real lesson from today's own failed deploy: without this, a task that can't
            # start (like the assign_public_ip bug above) doesn't fail fast — CDK's own
            # synth-time warning states plainly that CloudFormation can take up to 3 hours to
            # give up without it. rollback=True actually rolls the stack back automatically
            # once the circuit breaker trips, instead of just stopping and leaving it broken.
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
            # Real bug caught live: cdk deploy builds Docker images locally, and on an
            # Apple Silicon Mac that means ARM64 images — but Fargate defaults to x86_64,
            # so the container failed with "exec format error" the moment it tried to run
            # uvicorn, even though the image built and pushed successfully. Matching Fargate's
            # runtime to what's actually built avoids this, and ARM64 (Graviton) Fargate is
            # also genuinely ~20% cheaper per vCPU-hour than x86.
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )
        self.narration_service.target_group.configure_health_check(path="/health")
        narration_scaling = self.narration_service.service.auto_scale_task_count(min_capacity=1, max_capacity=4)
        # Request-count-based, same reasoning as understanding() above — also I/O-bound on
        # Bedrock. Lower target (10, not 20): narrate()'s worst case chains up to 3 retries, each
        # a generate() + verify() pair (see services/narration/narrate.py's MAX_RETRIES), so a
        # single request can occupy its thread for roughly 2-3x as long as understanding()'s
        # typical tool-calling turn — fewer concurrent requests fit per task before it should
        # scale out. Same caveat: a starting point, not a measured number, pending real Bedrock
        # latency data.
        narration_scaling.scale_on_request_count(
            "NarrationRequestScaling",
            requests_per_target=10,
            target_group=self.narration_service.target_group,
            scale_in_cooldown=Duration.seconds(60),
            scale_out_cooldown=Duration.seconds(30),
        )

        CfnOutput(self, "UnderstandingServiceUrl", value=self.understanding_service.load_balancer.load_balancer_dns_name)
        CfnOutput(self, "NarrationServiceUrl", value=self.narration_service.load_balancer.load_balancer_dns_name)
        CfnOutput(self, "MlflowServiceUrl", value=self.mlflow_service.load_balancer.load_balancer_dns_name)
        CfnOutput(self, "LangfuseSecretName", value=langfuse_secret.secret_name)
