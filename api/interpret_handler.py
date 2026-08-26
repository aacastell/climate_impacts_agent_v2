"""interpret() — ADR-004's fast call, restored to ADR-004's actual decision after a real,
acknowledged drift: "the query API never computes or extracts shading values; it only tells the
frontend which precomputed slice to load." interpret() itself does not read S3 or touch a
scientific value at all anymore — it returns real identifiers (resolved region, crop, warming
level, year, and each indicator's real output-field name) that the frontend uses to fetch the
matching precomputed file directly from CloudFront (see frontend/src/precomputedFetch.ts) and
parse it client-side. This also means this Lambda has no xarray/numpy/netCDF4 dependency at all
— see api/Dockerfile — unlike narrate_handler.py, which still needs one real server-side scalar
per fact (feeds the LLM narration + its verification gate, not a display concern).

The interpretation this returns carries lon/lat and the resolved year, not just a region name —
a deliberate real-backend refinement over frontend/src/api/types.ts's current QueryInterpretation
shape (region: string only), which predates any real backend and was written against mock data.
Carrying the resolved coordinates is what lets narrate() (see narrate_handler.py) be a genuine
pure function of the interpretation alone (ADR-004 Step 4) without a second, redundant geocode()
round-trip through understanding().

clarify() round-trips: per ADR-005's Accompanying decisions, "the workflow is stateful, the
compute layer stays stateless" — this function itself holds no state between calls; a query_id
and understanding()'s trace live in session_table (DynamoDB, TTL, see infra/stacks/api_stack.py)
instead. A fresh question with no query_id starts a new session on clarify(); a follow-up
carrying query_id + the user's answer resumes the stored trace by appending that answer as the
pending clarify call's toolResult (a real Bedrock Converse requirement, not a style choice — see
orchestrator.interpret()'s docstring) and continuing the same conversation.
"""

import json
import os
import time
import uuid

import httpx

from climate_pipeline.process.field_names import CROP_FIELDS, output_field_name

UNDERSTANDING_URL = os.environ.get("UNDERSTANDING_URL", "http://localhost:8000")
SESSION_TTL_SECONDS = 900  # 15 minutes — long enough for a real user to read and answer a clarifying question, short enough that DynamoDB's own TTL sweep clears stale sessions without any code here having to run a cleanup job.

# frontend indicator id -> (base_field, kind, unit). See climate_pipeline/process/field_names.py's
# FIELD_VARIANTS for why pr has both variants and tas doesn't.
_CLIMATE_INDICATORS = [
    ("temp_change", "tas", "absolute", "°C"),
    ("precip_change_abs", "pr", "absolute", "mm/day"),
    ("precip_change_pct", "pr", "percent", "% precip change"),
    ("consecutive_dry_days", "consecutive_dry_days", "absolute", "days"),
    ("extreme_heat_days", "extreme_heat_days", "absolute", "days"),
]

_DISCLAIMERS = [
    "Management is frozen at 2015 conditions (2015soc) — no adaptation is represented.",
    "A single climate model provides no climate-model uncertainty range. The yield figure comes "
    "from a single crop model (LPJmL) — pDSSAT is out of scope for this MVP.",
]

_PROVENANCE = {
    "dataVersion": "v2-0",
    "indicatorVersion": "v2-0",
    "climateModel": "GFDL-ESM4",
    "cropModel": "LPJmL",
    "scenario": "SSP3-7.0",
    "runSpecifier": "2015soc",
    "promptVersion": "understanding-v2-0",
}


def _refusal(reason: str, message: str) -> dict:
    return {"kind": "refusal", "reason": reason, "message": message}


def interpret(http_client, question: str, *, session_table=None, query_id: str | None = None, answer: str | None = None) -> dict:
    """session_table: a DynamoDB Table resource (boto3.resource("dynamodb").Table(...)), or a
    fake exposing the same get_item/put_item/delete_item(Key=...) surface in tests. None is only
    valid when this call can never hit a clarify() outcome (existing tests that only exercise
    resolved/refusal paths) — a real clarify() with session_table=None would raise, which is the
    right failure mode: silently dropping session state would be worse than an explicit error.

    query_id/answer: both set together, only on a resume call — the caller already has these
    from a prior clarify() response and the user's typed answer to it.
    """
    if query_id is not None:
        item = session_table.get_item(Key={"query_id": query_id}).get("Item")
        if item is None:
            return _refusal("session_expired", "This clarification session has expired or wasn't found — please ask your question again.")
        # Stored as a JSON string, not a native DynamoDB nested structure — real bug caught live:
        # boto3's Table resource rejects plain Python float anywhere in a nested Item (region
        # lon/lat from a real geocode() result, in this case) with "Float types are not
        # supported. Use Decimal types instead." Recursively converting every float in an
        # arbitrarily-nested Bedrock message trace to Decimal is exactly the kind of fragile
        # workaround worth avoiding — a plain string sidesteps DynamoDB's type system entirely.
        trace = json.loads(item["trace"])
        # A plain text turn, not a toolResult — real bug caught live: orchestrator.py's stored
        # trace already completes the toolResult turn for every toolUse in the clarify-triggering
        # assistant turn (including a placeholder for clarify's own toolUseId) before returning,
        # so that pairing is already satisfied. Appending a second toolResult for the same
        # toolUseId here was a real, confirmed ValidationException in production ("Expected
        # toolResult blocks..."). The user's answer to a clarifying question is just the next
        # normal conversational turn, same as a human's reply would be.
        trace.append({"role": "user", "content": [{"text": answer}]})
        original_question = item["original_question"]
        request_body = {"question": original_question, "trace": trace}
    else:
        original_question = question
        request_body = {"question": question}

    response = http_client.post(f"{UNDERSTANDING_URL}/interpret", json=request_body)
    response.raise_for_status()
    understanding_result = response.json()

    kind = understanding_result["kind"]
    if kind == "clarify":
        # Reuse the same query_id across multiple clarify() rounds on one conversation, rather
        # than minting a new one each time — the frontend only ever needs to track one id per
        # in-progress conversation, not one per round.
        active_query_id = query_id if query_id is not None else str(uuid.uuid4())
        session_table.put_item(Item={
            "query_id": active_query_id,
            "trace": json.dumps(understanding_result["trace"]),
            "tool_use_id": understanding_result["tool_use_id"],
            "original_question": original_question,
            "expires_at": int(time.time()) + SESSION_TTL_SECONDS,
        })
        return {"kind": "clarify", "query_id": active_query_id, "question": understanding_result["question"]}

    if query_id is not None:
        session_table.delete_item(Key={"query_id": query_id})  # conversation resolved or refused — session is done either way

    if kind == "refusal":
        return _refusal(understanding_result.get("reason", "unresolved"), understanding_result.get("message", "Could not resolve the question."))

    region = understanding_result["region"]
    crop_key = understanding_result["crop"]
    warming_level_c = understanding_result["warmingLevelC"]
    year = understanding_result["year"]
    lon, lat = region["lon"], region["lat"]

    if crop_key not in CROP_FIELDS:
        return _refusal("unsupported_crop", f"{crop_key!r} is not one of the four supported crops.")

    indicators = [
        {
            "id": indicator_id,
            "title": f"{indicator_id} at {warming_level_c}°C global warming",
            "unit": unit,
            # Real identifier only — the frontend derives the exact S3/CDN key
            # (processed/global/{outputField}/y{year}.nc) and fetches + parses it itself. No
            # value, no grid: this Lambda never touches the precomputed store (ADR-004).
            "outputField": output_field_name(base_field, field_kind),
        }
        for indicator_id, base_field, field_kind, unit in _CLIMATE_INDICATORS
    ]

    return {
        "kind": "answer",
        "interpretation": {
            "region": region["name"],
            "region_lon": lon,
            "region_lat": lat,
            "crop": crop_key,
            "warmingLevelC": warming_level_c,
            "year": year,
        },
        "climateMap": {"center": {"lon": lon, "lat": lat}, "zoom": 5, "indicators": indicators},
        "sectorMap": {
            "title": f"{crop_key} yield change at {warming_level_c}°C global warming",
            "unit": "% yield change",
            "outputField": output_field_name(crop_key, "percent"),
            "center": {"lon": lon, "lat": lat},
            "zoom": 5,
        },
        "disclaimers": list(_DISCLAIMERS),
        "provenance": dict(_PROVENANCE),
    }
