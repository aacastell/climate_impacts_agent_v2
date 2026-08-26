"""Real AWS Lambda entry point for narrate() — kept separate from interpret_lambda_handler.py
(see that module's own docstring for why) so this function's real xarray/netCDF4 dependency
(narrate() still reads real scalars server-side for its verification gate — ADR-004 Step 4) isn't
carried by interpret()'s cold start too.
"""

import json
import os
from pathlib import Path

import boto3
import httpx

from narrate_handler import narrate

BUCKET = os.environ.get("ISIMIP_BUCKET", "")
WORK_DIR_STR = os.environ.get("LAMBDA_WORK_DIR", "/tmp/work")

_s3 = boto3.client("s3")
_http_client = httpx.Client(timeout=30.0)


def _response(status_code: int, body: dict) -> dict:
    return {"statusCode": status_code, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def handler(event, context) -> dict:
    body = json.loads(event.get("body") or "{}")
    interpretation = body.get("interpretation", {})
    result = narrate(_s3, BUCKET, Path(WORK_DIR_STR), _http_client, interpretation)
    return _response(200, result)
