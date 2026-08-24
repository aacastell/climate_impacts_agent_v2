from aws_cdk import (
    CfnOutput,
    Stack,
    aws_codebuild as codebuild,
    aws_s3 as s3,
)
from constructs import Construct


class IsimipFetchBuildProjectStack(Stack):
    """CodeBuild project that runs the fetch stage of the offline scientific
    data pipeline — per ADR-006.

    Deliberately no webhook, unlike FrontendBuildProjectStack: this
    pipeline updates on ISIMIP/GGCMI's own release cadence, not on every
    push to main (see ADR-006 Step 7 — continuous triggering was rejected
    outright). Started manually via `scripts/run-codebuild.sh
    <this project's name>`, same script the frontend build already uses —
    it's already generic over project name, nothing to add there.

    Runs `pipeline/buildspec.yml`, scoped under `pipeline/` for the same
    reason `frontend/buildspec.yml` is scoped under `frontend/` — this
    builds the pipeline specifically, not "the repo."

    Requires the same GitHub context as FrontendBuildProjectStack
    (`-c githubOwner=<owner> -c githubRepo=<repo>`), and the same one-time
    account-level GitHub connection — already authorized, see
    infra/README.md.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        bucket: s3.IBucket,
        github_owner: str,
        github_repo: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project = codebuild.Project(
            self,
            "IsimipFetchBuildProject",
            # Fixed, predictable name — same reasoning as
            # ClimateImpactsFrontendBuild: scripts/run-codebuild.sh
            # references this directly.
            project_name="ClimateImpactsIsimipFetch",
            source=codebuild.Source.git_hub(
                owner=github_owner,
                repo=github_repo,
                # No webhook — see class docstring. This project is only
                # ever started explicitly (aws codebuild start-build), and
                # always builds whatever is currently on main, same as the
                # frontend build project's manual-invocation path.
            ),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
            ),
            build_spec=codebuild.BuildSpec.from_source_filename("pipeline/buildspec.yml"),
        )

        bucket.grant_read_write(project)

        CfnOutput(self, "BuildProjectName", value=project.project_name)
