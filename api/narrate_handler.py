"""narrate() — ADR-004's slower, independently stateless call. A pure function of the resolved
interpretation alone (ADR-004 Step 4): it does not receive anything interpret() computed, it
independently re-derives the evidence it needs from Phase 1's precomputed store and calls
narration() itself. Any backend instance can serve this call with no shared memory from the
interpret() call that produced the interpretation it's given.
"""

import os

import httpx

from climate_pipeline.query.lookup import lookup_value

NARRATION_URL = os.environ.get("NARRATION_URL", "http://localhost:8001")

_KG_M2_S1_TO_MM_PER_DAY = 86400.0


def narrate(s3, bucket: str, work_dir, http_client, interpretation: dict) -> dict:
    region_name = interpretation["region"]
    lon, lat = interpretation["region_lon"], interpretation["region_lat"]
    crop_key = interpretation["crop"]
    warming_level_c = interpretation["warmingLevelC"]
    year = interpretation["year"]

    temp_change_c = lookup_value(s3, bucket, "tas", "absolute", year, lon, lat, work_dir)
    precip_change_pct = lookup_value(s3, bucket, "pr", "percent", year, lon, lat, work_dir)
    extreme_heat_days = lookup_value(s3, bucket, "extreme_heat_days", "absolute", year, lon, lat, work_dir)
    consecutive_dry_days = lookup_value(s3, bucket, "consecutive_dry_days", "absolute", year, lon, lat, work_dir)
    yield_change_pct = lookup_value(s3, bucket, crop_key, "percent", year, lon, lat, work_dir)

    response = http_client.post(
        f"{NARRATION_URL}/narrate",
        json={
            "region_name": region_name,
            "crop_label": crop_key,
            "warming_level_c": warming_level_c,
            "climate_evidence": {
                "temp_change_c": round(temp_change_c, 2),
                "precip_change_pct": round(precip_change_pct, 2),
                "extreme_heat_days": round(extreme_heat_days, 2),
                "consecutive_dry_days": round(consecutive_dry_days, 2),
            },
            "yield_change_pct": round(yield_change_pct, 2),
        },
    )
    response.raise_for_status()
    return response.json()
