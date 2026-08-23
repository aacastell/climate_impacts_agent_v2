from aws_cdk import (
    CfnOutput,
    Stack,
    aws_cloudfront as cloudfront,
    aws_codebuild as codebuild,
    aws_iam as iam,
    aws_s3 as s3,
)
from constructs import Construct


class FrontendBuildProjectStack(Stack):
    """CodeBuild project that builds the frontend and uploads it to the
    hosting bucket, so the build runs on AWS compute rather than a
    developer's laptop.

    Separate stack from FrontendHostingStack deliberately: this is deploy
    tooling, not hosting infrastructure — it changes independently and
    carries different risk (see ADR-003's "Accompanying decisions").

    Runs the exact same scripts a human runs locally (scripts/build-frontend.sh,
    scripts/upload-frontend.sh, scripts/invalidate-cache.sh — see
    buildspec.yml) rather than reimplementing those steps here, so CodeBuild
    is just another caller of the same logic, not a second copy of it.

    Requires two CDK context values — the GitHub repo this pulls from isn't
    hardcoded, because it doesn't exist yet at the time this is written:

        cdk deploy -c githubOwner=<owner> -c githubRepo=<repo>

    Also requires a one-time GitHub connection authorized in this AWS
    account before CodeBuild can pull any GitHub source at all — see
    infra/README.md.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        bucket: s3.IBucket,
        distribution: cloudfront.IDistribution,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        github_owner = self.node.try_get_context("githubOwner")
        github_repo = self.node.try_get_context("githubRepo")
        if not github_owner or not github_repo:
            raise ValueError(
                "Missing required context: pass -c githubOwner=<owner> "
                "-c githubRepo=<repo>. There's no default — the repo this "
                "stack depends on doesn't exist yet."
            )

        project = codebuild.Project(
            self,
            "FrontendBuildProject",
            source=codebuild.Source.git_hub(
                owner=github_owner,
                repo=github_repo,
                webhook=True,
                webhook_filters=[
                    codebuild.FilterGroup.in_event_of(
                        codebuild.EventAction.PUSH
                    ).and_branch_is("main"),
                ],
            ),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
            ),
            build_spec=codebuild.BuildSpec.from_source_filename("buildspec.yml"),
        )

        bucket.grant_read_write(project)
        project.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudfront:CreateInvalidation"],
                resources=[
                    self.format_arn(
                        service="cloudfront",
                        region="",
                        resource="distribution",
                        resource_name=distribution.distribution_id,
                    ),
                ],
            )
        )

        CfnOutput(self, "BuildProjectName", value=project.project_name)
