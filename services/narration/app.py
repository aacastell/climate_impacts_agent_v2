"""RAG + narration + verification, bundled as one independently deployable service — resolved
service-boundary decision, see docs/adr/adr-007-narration-verification-gate.md's Accompanying
decisions: RAG's only consumer is narration, so no separate network hop for it.

Real Bedrock generation/verification client; corpus is honestly empty pending real literature
curation (see corpus.py) — retrieval will return no passages until that's filled in, which is
correct, not broken.
"""

import logging
import os

import boto3
from fastapi import FastAPI
from pydantic import BaseModel

from corpus import CORPUS
from eval_capture import capture
from model_client import BedrockConverseNarrationClient
from narrate import narrate
from retrieval import retrieve

app = FastAPI(title="narration()")
logger = logging.getLogger(__name__)

MODEL_ID = os.environ.get("NARRATION_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")

_bedrock_runtime = boto3.client("bedrock-runtime")
_model_client = BedrockConverseNarrationClient(_bedrock_runtime, MODEL_ID)


def _retrieve_fn(query: str) -> list[dict]:
    return retrieve(_bedrock_runtime, EMBEDDING_MODEL_ID, CORPUS, query)


class ClimateEvidence(BaseModel):
    temp_change_c: float
    precip_change_pct: float
    extreme_heat_days: float
    consecutive_dry_days: float


class NarrateRequest(BaseModel):
    region_name: str
    crop_label: str
    warming_level_c: float
    climate_evidence: ClimateEvidence
    yield_change_pct: float


@app.post("/narrate")
def narrate_endpoint(request: NarrateRequest) -> dict:
    climate_evidence = request.climate_evidence.model_dump()
    result = narrate(
        _model_client,
        _retrieve_fn,
        request.region_name,
        request.crop_label,
        request.warming_level_c,
        climate_evidence,
        request.yield_change_pct,
    )
    # Every call, not just SCIENTIFIC_DISAGREEMENT ones — PASS cases are the denominator any
    # later accuracy metric needs (see eval_capture.py). Wrapped: eval/observability logging is
    # secondary to the real answer this endpoint exists to return — a capture failure (e.g. the
    # MLflow backend being unreachable) must never turn an already-successful narration into a
    # 500 the caller never sees the actual result for.
    try:
        capture(result, request.region_name, request.crop_label, request.warming_level_c, climate_evidence, request.yield_change_pct)
    except Exception:
        logger.exception("eval_capture.capture() failed — narration result is still returned")
    return result


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
