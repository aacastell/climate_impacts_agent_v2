from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_logs as logs,
    aws_s3 as s3,
)
from constructs import Construct


class ModelServicesStack(Stack):
    """Real ECS/Fargate infrastructure for understanding() and narration() — ADR-005's resolved
    compute-topology decision: these two get scalable, persistent compute because each holds real
    state worth amortizing across requests (a model client with its own connection/latency
    profile — the fine-tuned model checkpoint once that exists for understanding(); retrieval
    embeddings and the corpus for narration()). The orchestration/API tier does not get this
    treatment (Lambda, see ADR-005) because it has nothing comparable to amortize.

    Deliberately NOT deployed as part of tonight's work — see docs/overnight-2026-08-25.md. This
    is real, reviewable infrastructure-as-code, checked via the CDK Python testing framework
    (Template.from_stack, no real AWS calls), not `cdk deploy`. Standing up real, billed ECS
    clusters, load balancers, and NAT-free VPC networking unsupervised, overnight, is a decision
    that belongs to whoever is going to see the AWS bill — not something to commit to blind.

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
            self, "ModelServicesLogGroup", log_group_name="/climate-impacts/model-services", retention=logs.RetentionDays.ONE_MONTH
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
            iam.PolicyStatement(actions=["geo:SearchPlaceIndexForText"], resources=["*"])
        )
        isimip_data_bucket.grant_read(understanding_task_role)

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
                    # Real Place Index resource name — see infra/stacks/geocode_index_stack.py
                    # once that's provisioned; not yet wired here (still the temporary CLI-created
                    # test index from tonight's earlier verification work).
                    "LOCATION_INDEX_NAME": "geocode-verification-test",
                },
            ),
            public_load_balancer=True,
            listener_port=80,
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

        narration_task_role = iam.Role(
            self, "NarrationTaskRole", assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com")
        )
        narration_task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:Converse", "bedrock:ConverseStream"],
                resources=["*"],
            )
        )

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
            ),
            public_load_balancer=True,
            listener_port=80,
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
