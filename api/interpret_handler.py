"""interpret() — ADR-004's fast call. Resolves a question via understanding() (real HTTP call to
that service), then reads every value from Phase 1's precomputed store directly (no LLM ever
touches a scientific value — ADR-005 Step 3).

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

from climate_pipeline.process.run import CROP_FIELDS
from climate_pipeline.query.lookup import lookup_grid, lookup_value

UNDERSTANDING_URL = os.environ.get("UNDERSTANDING_URL", "http://localhost:8000")
SESSION_TTL_SECONDS = 900  # 15 minutes — long enough for a real user to read and answer a clarifying question, short enough that DynamoDB's own TTL sweep clears stale sessions without any code here having to run a cleanup job.

# frontend indicator id -> (base_field, kind, unit). See climate_pipeline/process/run.py's
# FIELD_VARIANTS for why pr has both variants and tas doesn't.
_CLIMATE_INDICATORS = [
    ("temp_change", "tas", "absolute", "°C"),
    ("precip_change_abs", "pr", "absolute", "mm/day"),
    ("precip_change_pct", "pr", "percent", "% precip change"),
    ("consecutive_dry_days", "consecutive_dry_days", "absolute", "days"),
    ("extreme_heat_days", "extreme_heat_days", "absolute", "days"),
]

# 1 kg/m^2 of water = 1mm depth; pr is stored in the canonical store as a per-second flux (CF/
# ISIMIP convention, kg m-2 s-1) — converting to the human-readable mm/day the frontend displays
# is a presentation-layer concern, done here at query time, not baked into the precomputed store.
_KG_M2_S1_TO_MM_PER_DAY = 86400.0

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


def _indicator_value(s3, bucket: str, base_field: str, kind: str, year: int, lon: float, lat: float, work_dir):
    value = lookup_value(s3, bucket, base_field, kind, year, lon, lat, work_dir)
    if base_field == "pr" and kind == "absolute":
        value *= _KG_M2_S1_TO_MM_PER_DAY
    return value


# Real regional shading, not decoration: the frontend used to render a single colored dot
# regardless of what "region" meant, even though the precomputed store has always held a full
# global grid per field (see pipeline/climate_pipeline/query/lookup.py's grid_patch — the whole
# small object lookup_value already downloads, just read more of it). RADIUS_DEG=2.0 is a
# real-world-meaningful box (≈220km at the equator, real ISIMIP 0.5° cells), not an arbitrary
# pixel count — kept small deliberately so the response payload stays small (see
# _indicator_grid's own docstring).
_GRID_RADIUS_DEG = 2.0


def _indicator_grid(s3, bucket: str, base_field: str, kind: str, year: int, lon: float, lat: float, work_dir) -> dict:
    """Same real precomputed data _indicator_value reads, as a small spatial patch instead of one
    scalar — same unit conversion, same convert-then-round order as the scalar path (see
    grid_patch's own docstring for why the order matters), so the map's shading and its own
    labeled value are never in different units or subtly different numbers from rounding twice."""
    grid = lookup_grid(s3, bucket, base_field, kind, year, lon, lat, work_dir, radius_deg=_GRID_RADIUS_DEG)
    convert = (lambda v: v * _KG_M2_S1_TO_MM_PER_DAY) if (base_field == "pr" and kind == "absolute") else (lambda v: v)
    return {
        **grid,
        "values": [[None if v is None else round(convert(v), 4) for v in row] for row in grid["values"]],
    }


def interpret(s3, bucket: str, work_dir, http_client, question: str, *, session_table=None, query_id: str | None = None, answer: str | None = None) -> dict:
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
        trace.append({"role": "user", "content": [{"toolResult": {"toolUseId": item["tool_use_id"], "content": [{"text": answer}]}}]})
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
            "value": round(_indicator_value(s3, bucket, base_field, field_kind, year, lon, lat, work_dir), 4),
            "grid": _indicator_grid(s3, bucket, base_field, field_kind, year, lon, lat, work_dir),
        }
        for indicator_id, base_field, field_kind, unit in _CLIMATE_INDICATORS
    ]
    yield_change_pct = round(_indicator_value(s3, bucket, crop_key, "percent", year, lon, lat, work_dir), 2)
    yield_grid = _indicator_grid(s3, bucket, crop_key, "percent", year, lon, lat, work_dir)

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
            "value": yield_change_pct,
            "grid": yield_grid,
            "center": {"lon": lon, "lat": lat},
            "zoom": 5,
        },
        "disclaimers": list(_DISCLAIMERS),
        "provenance": dict(_PROVENANCE),
    }
