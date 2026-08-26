"""Real AWS Lambda entry point for interpret() — split into its own module (not shared with
narrate_lambda_handler.py) for a real reason, not just tidiness: interpret_handler.py no longer
touches the precomputed store at all (ADR-004's restored decision), so this function's cold start
should never import narrate_handler.py's own xarray/netCDF4 dependency chain (still real and
needed there — narrate() re-derives evidence server-side for its verification gate). A single
shared lambda_handler.py that imported both, as this project did before, meant every cold start
of *either* function paid for both handlers' combined imports regardless of which one actually
ran.
"""

import json
import os

import boto3
import httpx

from interpret_handler import interpret

SESSION_TABLE_NAME = os.environ.get("SESSION_TABLE_NAME", "")

_http_client = httpx.Client(timeout=30.0)
_session_table = boto3.resource("dynamodb").Table(SESSION_TABLE_NAME) if SESSION_TABLE_NAME else None


def _response(status_code: int, body: dict) -> dict:
    return {"statusCode": status_code, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def handler(event, context) -> dict:
    body = json.loads(event.get("body") or "{}")
    question = body.get("question", "")
    result = interpret(
        _http_client, question,
        session_table=_session_table, query_id=body.get("query_id"), answer=body.get("answer"),
    )
    return _response(200, result)
