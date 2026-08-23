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
    frontend/buildspec.yml) rather than reimplementing those steps here, so
    CodeBuild is just another caller of the same logic, not a second copy
    of it. buildspec.yml lives under frontend/, not at repo root: this
    stack builds the frontend specifically, not "the repo" — root would
    misrepresent that once a second buildable component (an API tier, a
    data pipeline) exists here too.

    Requires two values — the GitHub repo this pulls from isn't hardcoded,
    because it doesn't exist yet at the time this is written. app.py only
    constructs this stack at all when both are supplied via CDK context:

        cdk deploy ClimateImpactsFrontendBuildProject -c githubOwner=<owner> -c githubRepo=<repo>

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
        github_owner: str,
        github_repo: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project = codebuild.Project(
            self,
            "FrontendBuildProject",
            # Fixed, predictable name — scripts/run-codebuild.sh
            # references this directly rather than needing this stack's
            # own outputs.json (which would require GitHub context just to
            # look up a name).
            project_name="ClimateImpactsFrontendBuild",
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
                # upload-frontend.sh / invalidate-cache.sh need the bucket
                # name and distribution ID. Locally those come from
                # infra/outputs.json, written by provision-infra.sh on the
                # same machine — but that file is gitignored and never
                # reaches this container's fresh checkout, so it's baked in
                # here directly instead. CDK already knows both values at
                # this point; no file handoff needed.
                environment_variables={
                    "FRONTEND_BUCKET_NAME": codebuild.BuildEnvironmentVariable(
                        value=bucket.bucket_name
                    ),
                    "FRONTEND_DISTRIBUTION_ID": codebuild.BuildEnvironmentVariable(
                        value=distribution.distribution_id
                    ),
                },
            ),
            build_spec=codebuild.BuildSpec.from_source_filename("frontend/buildspec.yml"),
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
