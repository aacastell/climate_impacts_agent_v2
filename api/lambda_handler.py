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
SESSION_TABLE_NAME = os.environ.get("SESSION_TABLE_NAME", "")

_s3 = boto3.client("s3")
_http_client = httpx.Client(timeout=30.0)
_session_table = boto3.resource("dynamodb").Table(SESSION_TABLE_NAME) if SESSION_TABLE_NAME else None


def _response(status_code: int, body: dict) -> dict:
    return {"statusCode": status_code, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def interpret_lambda_handler(event, context) -> dict:
    body = json.loads(event.get("body") or "{}")
    question = body.get("question", "")
    result = interpret(
        _s3, BUCKET, Path(WORK_DIR_STR), _http_client, question,
        session_table=_session_table, query_id=body.get("query_id"), answer=body.get("answer"),
    )
    return _response(200, result)


def narrate_lambda_handler(event, context) -> dict:
    body = json.loads(event.get("body") or "{}")
    interpretation = body.get("interpretation", {})
    result = narrate(_s3, BUCKET, Path(WORK_DIR_STR), _http_client, interpretation)
    return _response(200, result)
