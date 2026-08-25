"""understanding() as an independently deployable inference service — see ADR-005:
"understanding() is planned as an independently deployable inference service, not folded into the
API process." Real FastAPI service, real tool-calling via orchestrator.interpret(), currently
backed by Claude on Bedrock (see model_client.py on why that's the current implementation, not a
compromise — the interface is what ADR-005 actually commits to, the model behind it is explicitly
swappable, and that's exactly what lets the real fine-tuned checkpoint drop in later).
"""

import json
import os

import boto3
from fastapi import FastAPI
from pydantic import BaseModel

from model_client import BedrockConverseUnderstandingClient
from orchestrator import interpret

app = FastAPI(title="understanding()")

BUCKET = os.environ["ISIMIP_BUCKET"]
LOCATION_INDEX_NAME = os.environ["LOCATION_INDEX_NAME"]
# Real, currently-available model on this account's Bedrock access (verified live via
# bedrock:ListFoundationModels) — not the fine-tuned model ADR-005 ultimately calls for, which
# doesn't exist yet. See model_client.py. The us.* prefix is a real requirement, not style: this
# account's on-demand Bedrock access requires an inference profile ID for this model, not the raw
# model ID (confirmed live — a raw model ID here fails with "Invocation... with on-demand
# throughput isn't supported").
MODEL_ID = os.environ.get("UNDERSTANDING_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

_bedrock_runtime = boto3.client("bedrock-runtime")
_location = boto3.client("location")
_s3 = boto3.client("s3")
_model_client = BedrockConverseUnderstandingClient(_bedrock_runtime, MODEL_ID)

_gwl_year_table_cache: list[dict] | None = None


def _load_gwl_year_table() -> list[dict]:
    """Cached for the life of the process — the table only changes when process_gwl_year_table
    reruns (tas data changes), not per request."""
    global _gwl_year_table_cache
    if _gwl_year_table_cache is None:
        obj = _s3.get_object(Bucket=BUCKET, Key="processed/global/gwl_year_table.json")
        _gwl_year_table_cache = json.loads(obj["Body"].read())
    return _gwl_year_table_cache


class InterpretRequest(BaseModel):
    question: str
    # Non-empty only on a clarify()-resume call — the caller (api/interpret_handler.py) is
    # responsible for retrieving this from its own short-lived session store and appending the
    # user's answer as the pending clarify call's toolResult before sending it back here. See
    # orchestrator.interpret()'s docstring and ADR-005's query_id/session-store design.
    trace: list | None = None


@app.post("/interpret")
def interpret_endpoint(request: InterpretRequest) -> dict:
    gwl_year_table = _load_gwl_year_table()
    trace = request.trace if request.trace is not None else []
    result = interpret(_model_client, _location, LOCATION_INDEX_NAME, gwl_year_table, request.question, trace=trace)
    # Always returned, not just on clarify — simpler contract than a conditional response shape,
    # and the caller only needs to act on it when result["kind"] == "clarify" anyway.
    return {**result, "trace": trace}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
