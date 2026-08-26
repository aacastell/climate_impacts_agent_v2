"""The real, final step of understanding()'s fine-tuning story: submit an actual Bedrock
CreateModelCustomizationJob. Everything upstream of this (build_training_dataset.py, the
BedrockFineTuneRole in infra/stacks/model_services_stack.py) exists so that once real training
data is judged sufficient, running this script really is the entire remaining action — not a
placeholder for one.

Real, confirmed-live findings baked into the defaults below, not guessed:
- `amazon.nova-pro-v1:0:300k` supports FINE_TUNING (plus DISTILLATION, PREFERENCE_FINE_TUNING)
  *only* in us-east-1, not this project's home region (us-east-2) — confirmed via
  `aws bedrock list-foundation-models --region <region> --query
  "modelSummaries[?customizationsSupported[0]!=null]"` across us-east-1/us-east-2/us-west-2.
  Nova Pro is this project's real standing model (see model_services_stack.py's
  _TEMPORARY_MODEL_ID), so it's the real default here — not Claude Haiku, which is still blocked
  on an unsubmitted use-case form and isn't even Bedrock-fine-tunable the same way in this
  account's regions today.
- Dataset schema (`bedrock-conversation-2024`) confirmed live against
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-customization-prepare.html.

One real, flagged uncertainty this script does NOT paper over: whether Bedrock's FINE_TUNING
validator accepts toolUse/toolResult content blocks (see build_training_dataset.py's docstring) is
unconfirmed. Run this once against a small dataset first and read the job's real failure reason
(if any) via `aws bedrock get-model-customization-job` before trusting it at scale.

Run with:
  python trigger_finetune_job.py \
    --dataset-s3-uri s3://<bucket>/finetune/understanding/dataset.jsonl \
    --output-s3-uri s3://<bucket>/finetune/understanding/output/ \
    --role-arn <BedrockFineTuneRoleArn CDK output>
"""

import argparse
import json

import boto3

REGION = "us-east-1"  # the only region Nova Pro's FINE_TUNING is real in — see this file's docstring
BASE_MODEL_IDENTIFIER = "amazon.nova-pro-v1:0:300k"


def trigger_job(dataset_s3_uri: str, output_s3_uri: str, role_arn: str, job_name: str, hyperparameters: dict | None = None) -> dict:
    bedrock = boto3.client("bedrock", region_name=REGION)
    kwargs = {
        "jobName": job_name,
        "customModelName": job_name,
        "roleArn": role_arn,
        "baseModelIdentifier": BASE_MODEL_IDENTIFIER,
        "trainingDataConfig": {"s3Uri": dataset_s3_uri},
        "outputDataConfig": {"s3Uri": output_s3_uri},
    }
    if hyperparameters:
        kwargs["hyperParameters"] = hyperparameters
    return bedrock.create_model_customization_job(**kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-s3-uri", required=True)
    parser.add_argument("--output-s3-uri", required=True)
    parser.add_argument("--role-arn", required=True, help="BedrockFineTuneRoleArn from model_services_stack.py's CfnOutput")
    parser.add_argument("--job-name", default="understanding-finetune")
    args = parser.parse_args()

    response = trigger_job(args.dataset_s3_uri, args.output_s3_uri, args.role_arn, args.job_name)
    print(json.dumps(response, default=str, indent=2))
    print(
        f"\nTrack progress with:\n  aws bedrock get-model-customization-job "
        f"--job-identifier {args.job_name} --region {REGION}"
    )


if __name__ == "__main__":
    main()
