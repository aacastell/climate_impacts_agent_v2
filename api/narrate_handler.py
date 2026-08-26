"""narrate() — ADR-004's slower, independently stateless call. A pure function of the resolved
interpretation alone (ADR-004 Step 4): it does not receive anything interpret() computed, it
independently re-derives the evidence it needs from Phase 1's precomputed store and calls
narration() itself. Any backend instance can serve this call with no shared memory from the
interpret() call that produced the interpretation it's given.
"""

import os

import httpx

from climate_pipeline.process.covariation import driver_covariation as compute_driver_covariation
from climate_pipeline.query.lookup import lookup_grid, lookup_value

NARRATION_URL = os.environ.get("NARRATION_URL", "http://localhost:8001")

_KG_M2_S1_TO_MM_PER_DAY = 86400.0

# (evidence key -> (base_field, kind)) for the four climate drivers narration's verification gate
# checks the mechanism against — same fields as the scalar climate_evidence lookups below, kept as
# one mapping so the two can't silently drift apart (a fifth field added to one and not the other).
_DRIVER_FIELDS = {
    "temp_change_c": ("tas", "absolute"),
    "precip_change_pct": ("pr", "percent"),
    "extreme_heat_days": ("extreme_heat_days", "absolute"),
    "consecutive_dry_days": ("consecutive_dry_days", "absolute"),
}


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

    # Real, disclosed cost of the driver co-variation check (docs/adr/adr-007-narration-
    # verification-gate.md's Update): a grid-patch fetch per driver plus the yield field, on top
    # of the scalar lookups above — download_field_window() caches by local file, so this reuses
    # the same downloads lookup_value() already made rather than doubling S3 traffic.
    driver_grids = {
        evidence_key: lookup_grid(s3, bucket, base_field, kind, year, lon, lat, work_dir)
        for evidence_key, (base_field, kind) in _DRIVER_FIELDS.items()
    }
    yield_grid = lookup_grid(s3, bucket, crop_key, "percent", year, lon, lat, work_dir)
    driver_covariation = compute_driver_covariation(driver_grids, yield_grid)

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
            "driver_covariation": driver_covariation,
        },
    )
    response.raise_for_status()
    return response.json()
