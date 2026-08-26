# A real, self-hosted MLflow tracking server — not a stub. Replaces the ephemeral
# sqlite-inside-the-narration-container backend (wiped on every task restart, no UI, no
# external access) with a real service: SQLite on a persistent EFS volume for run/experiment
# metadata, S3 for artifacts. See infra/stacks/mlflow_stack.py for the real infrastructure.
FROM python:3.12-slim

RUN pip install --no-cache-dir mlflow==2.16.2 boto3

EXPOSE 5000

# --backend-store-uri points at a file under the EFS mount (infra/stacks/mlflow_stack.py mounts
# it at /mlflow-data) — real persistence across task restarts and redeploys, unlike the
# container's own ephemeral filesystem. --default-artifact-root is a real S3 prefix, matching
# every other real data store in this project.
CMD ["sh", "-c", "mlflow server --backend-store-uri sqlite:////mlflow-data/mlflow.db --default-artifact-root ${MLFLOW_ARTIFACT_ROOT} --host 0.0.0.0 --port 5000"]
