"""interpret() — ADR-004's fast, stateless call. Resolves a question via understanding() (real
HTTP call to that service), then reads every value from Phase 1's precomputed store directly (no
LLM ever touches a scientific value — ADR-005 Step 3).

The interpretation this returns carries lon/lat and the resolved year, not just a region name —
a deliberate real-backend refinement over frontend/src/api/types.ts's current QueryInterpretation
shape (region: string only), which predates any real backend and was written against mock data.
Carrying the resolved coordinates is what lets narrate() (see narrate_handler.py) be a genuine
pure function of the interpretation alone (ADR-004 Step 4) without a second, redundant geocode()
round-trip through understanding().
"""

import os

import httpx

from climate_pipeline.process.run import CROP_FIELDS
from climate_pipeline.query.lookup import lookup_value

UNDERSTANDING_URL = os.environ.get("UNDERSTANDING_URL", "http://localhost:8000")

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


def interpret(s3, bucket: str, work_dir, http_client, question: str) -> dict:
    response = http_client.post(f"{UNDERSTANDING_URL}/interpret", json={"question": question})
    response.raise_for_status()
    understanding_result = response.json()

    kind = understanding_result["kind"]
    if kind == "clarify":
        return {"kind": "clarify", "question": understanding_result["question"]}
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
        }
        for indicator_id, base_field, field_kind, unit in _CLIMATE_INDICATORS
    ]
    yield_change_pct = round(_indicator_value(s3, bucket, crop_key, "percent", year, lon, lat, work_dir), 2)

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
            "center": {"lon": lon, "lat": lat},
            "zoom": 5,
        },
        "disclaimers": list(_DISCLAIMERS),
        "provenance": dict(_PROVENANCE),
    }
