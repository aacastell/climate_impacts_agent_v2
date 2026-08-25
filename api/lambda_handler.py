"""Real AWS Lambda entry points for interpret()/narrate() — the orchestration tier ADR-005 puts
on Lambda specifically because it has nothing persistent to amortize (see docs/roadmap.md Phase 1
and ADR-005's compute-topology Accompanying decision). Thin wrappers only: all real logic lives in
interpret_handler.py/narrate_handler.py, kept separate from AWS-specific event/response shaping so
those stay unit-testable without any Lambda runtime involved (already proven — see tests/).
"""

import json
import os
from pathlib import Path

import boto3
import httpx

from interpret_handler import interpret
from narrate_handler import narrate

BUCKET = os.environ.get("ISIMIP_BUCKET", "")
WORK_DIR_STR = os.environ.get("LAMBDA_WORK_DIR", "/tmp/work")

_s3 = boto3.client("s3")
_http_client = httpx.Client(timeout=30.0)


def _response(status_code: int, body: dict) -> dict:
    return {"statusCode": status_code, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def interpret_lambda_handler(event, context) -> dict:
    body = json.loads(event.get("body") or "{}")
    question = body.get("question", "")
    result = interpret(_s3, BUCKET, Path(WORK_DIR_STR), _http_client, question)
    return _response(200, result)


def narrate_lambda_handler(event, context) -> dict:
    body = json.loads(event.get("body") or "{}")
    interpretation = body.get("interpretation", {})
    result = narrate(_s3, BUCKET, Path(WORK_DIR_STR), _http_client, interpretation)
    return _response(200, result)
