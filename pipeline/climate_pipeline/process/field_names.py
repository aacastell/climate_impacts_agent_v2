"""The real, minimal subset of process/run.py's own constants/functions that query-time
consumers (api/interpret_handler.py, climate_pipeline/query/lookup.py) actually need — split out
so importing them doesn't pull in process/run.py's own heavy dependency chain (xarray, dask via
its own imports, httpx via climate_pipeline.fetch.agriculture) for what is, for those callers,
just a couple of pure lookups. Real bug this fixes: api/interpret_handler.py used to import
CROP_FIELDS from process/run.py directly, which was part of why that Lambda's cold-start image
was carrying dependencies (dvc[s3], dask) it never actually used.

process/run.py itself imports CROP_FIELDS/FIELD_VARIANTS/output_field_name from here now, not the
other way around — this module has no reverse dependency on it.
"""

from climate_pipeline.fetch.agriculture import CROPS

CROP_FIELDS = list(CROPS)

# Which change-kind(s) each field gets — absolute change (always), plus percent change where a
# ratio-scale reading is scientifically valid (see process/run.py's module docstring for the
# tas-has-no-percent-counterpart reasoning this encodes).
FIELD_VARIANTS = {
    "tas": ["absolute"],
    "pr": ["absolute", "percent"],
    "consecutive_dry_days": ["absolute"],
    "extreme_heat_days": ["absolute"],
    **{crop: ["absolute", "percent"] for crop in CROP_FIELDS},
}


def output_field_name(base_field: str, kind: str) -> str:
    variants = FIELD_VARIANTS[base_field]
    if len(variants) == 1:
        return base_field
    return f"{base_field}_{'abs' if kind == 'absolute' else 'pct'}"
