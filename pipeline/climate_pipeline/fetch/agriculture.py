"""Fetches ISIMIP LPJmL crop yield data for one crop and window, streaming straight to S3.

Scope: LPJmL only. pDSSAT is dropped entirely for this MVP — verified against
ISIMIP's real catalog that it has no SSP3-7.0 output at all for GFDL-ESM4, so
it can't contribute to a future/warming-level projection under this system's
own climate model and scenario. Accepted consequence: no second crop model to
range yield projections against, until this is revisited. See root README's
Scope section.
"""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from climate_pipeline.fetch.isimip_client import only_file, search_dataset
from climate_pipeline.fetch.manifest import write_manifest
from climate_pipeline.fetch.profiling import record_run
from climate_pipeline.fetch.stream_to_s3 import stream_file_to_s3

WINDOWS = {"baseline": "historical", "future": "ssp370"}
SENS_SCENARIO = {"baseline": "default", "future": "2015co2"}

# Same crop vocabulary as frontend/src/api/types.ts's Crop type — one
# identifier set spanning the whole system, not a separate one here.
# ISIMIP codes verified live against the real catalog: LPJmL publishes rice
# as two separate growing periods (ri1, ri2) — a real agronomic distinction,
# not a data-quality issue. ri1 (first/primary growing period) is used here;
# whether/how to combine with ri2 is a scientific-spec decision, not this
# module's to make.
CROPS = {
    "maize": "mai",
    "spring_wheat": "swh",
    "soy": "soy",
    "rice": "ri1",
}


def fetch_agriculture(crop: str, window: str, bucket: str, manifest_dir: Path) -> Path:
    """Stream one crop's LPJmL yield dataset (rainfed) for a given window into S3.

    Args: crop — one of CROPS' keys. window — "baseline" or "future" (see WINDOWS).
        bucket — destination S3 bucket. manifest_dir — where to write the DVC-tracked manifest.
    Returns: path to the written manifest (the actual DVC stage output — see ADR-006 Step 8).
    """
    started_at = datetime.now(UTC)
    scenario = WINDOWS[window]
    dataset = search_dataset(
        product="OutputData",
        sector="agriculture",
        model="lpjml",
        crop=CROPS[crop],
        variable="yield",
        irrigation="noirr",
        soc_scenario="2015soc",
        sens_scenario=SENS_SCENARIO[window],
        climate_scenario=scenario,
    )
    file_entry = only_file(dataset)

    key = f"raw/agriculture/lpjml/{crop}/{scenario}/{file_entry['name']}"
    manifest = stream_file_to_s3(file_entry, bucket, key)

    record_run(bucket, f"lpjml_{crop}_{window}", started_at, [manifest])

    return write_manifest(manifest, manifest_dir / f"lpjml_{crop}_{window}.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crop", required=True, choices=list(CROPS))
    parser.add_argument("--window", required=True, choices=list(WINDOWS))
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--manifest-dir", required=True, type=Path)
    args = parser.parse_args()
    path = fetch_agriculture(args.crop, args.window, args.bucket, args.manifest_dir)
    print(f"Wrote manifest: {path}")


if __name__ == "__main__":
    main()
