#!/usr/bin/env bash
# Verifies the AWS CLI is present and credentials are valid, failing fast
# with a clear message rather than letting a later AWS call fail
# confusingly. Called by every other AWS-touching script in this
# directory, not just deploy.sh, so each one is correct run standalone.
set -euo pipefail

if ! command -v aws >/dev/null 2>&1; then
  echo "AWS CLI not found. Install it and configure credentials first." >&2
  exit 1
fi

# Defaults to the "dev" SSO profile configured for local development, but
# only if it actually exists and nothing else was already specified. In an
# environment like CodeBuild, there's no "dev" profile at all — credentials
# come from the attached IAM role instead — so forcing that default there
# would break authentication rather than skip it.
if [ -z "${AWS_PROFILE:-}" ] && aws configure list-profiles 2>/dev/null | grep -qx "dev"; then
  export AWS_PROFILE="dev"
fi

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  if [ -n "${AWS_PROFILE:-}" ]; then
    echo "No valid AWS credentials for profile '$AWS_PROFILE'. Run 'aws sso login --profile $AWS_PROFILE' (or 'aws configure') first." >&2
  else
    echo "No valid AWS credentials found (no AWS_PROFILE set, and no attached role/instance credentials worked)." >&2
  fi
  exit 1
fi

echo "==> AWS credentials OK (profile: ${AWS_PROFILE:-<none, using attached role>})"
