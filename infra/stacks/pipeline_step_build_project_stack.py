from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_codebuild as codebuild,
    aws_s3 as s3,
)
from constructs import Construct


class PipelineStepBuildProjectStack(Stack):
    """One fully independent CodeBuild project for exactly one pipeline step — one fetch stage,
    or one process field. Not a shared project with a parameterized trigger: each instance's
    command is baked into its own project definition as a fixed RUN_CMD environment variable, so
    triggering it is just `aws codebuild start-build --project-name <this step's name>`, nothing
    passed at invocation time.

    This replaced a single shared CodeBuild project (ClimateImpactsIsimipFetch) whose stages were
    selected via a DVC_TARGET override at build time. That caused real, unwanted coupling: `dvc
    repro <target>` walks the whole dependency graph, and since dvc.lock is never committed to
    git, a fresh CodeBuild checkout has no record of what other stages already did — so any single
    target silently re-executed its entire upstream chain every time. Real profiling also showed
    the old monolithic process stage didn't fit the account's ~45-minute CodeBuild cap at all. Full
    per-step separation fixes both: no stage can ever touch another's work as a side effect, and
    each step is sized to fit comfortably inside that cap on its own.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        project_name: str,
        run_cmd: str,
        bucket: s3.IBucket,
        github_owner: str,
        github_repo: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project = codebuild.Project(
            self,
            "BuildProject",
            project_name=project_name,
            source=codebuild.Source.git_hub(
                owner=github_owner,
                repo=github_repo,
                # No webhook, same reasoning as the fetch/frontend build projects before this —
                # this pipeline updates on ISIMIP/GGCMI's own release cadence (ADR-006 Step 7),
                # not on every push. Always builds whatever's currently on main.
            ),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                # MEDIUM, not the default SMALL — this project's real transfer/compute volume
                # (tens of GB for fetch steps, large in-memory grids for process steps) needs more
                # than the frontend build's few MB.
                compute_type=codebuild.ComputeType.MEDIUM,
                environment_variables={
                    "RUN_CMD": codebuild.BuildEnvironmentVariable(value=run_cmd),
                },
            ),
            # Explicit generous bound — the account's real ~45-minute cap overrides this
            # regardless (confirmed against real build records), but an explicit value here is
            # still correct so this project's own configuration isn't silently misleading.
            timeout=Duration.hours(4),
            build_spec=codebuild.BuildSpec.from_source_filename("pipeline/buildspec.yml"),
        )

        bucket.grant_read_write(project)

        CfnOutput(self, "BuildProjectName", value=project.project_name)
