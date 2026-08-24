"""Fetches one ISIMIP climate driver variable for one window, streaming straight to S3.

Scope: temperature (tas) and precipitation (pr) only, for now — matching the two
climate drivers already wired into the frontend's mock indicators. Extreme-heat-day
and dry-day counts are derived indicators, not raw ISIMIP variables fetched directly;
how they get computed belongs to the process stage, not fetch.
"""

import argparse
from pathlib import Path

from climate_pipeline.fetch.isimip_client import file_for_year_range, search_dataset
from climate_pipeline.fetch.manifest import write_manifest
from climate_pipeline.fetch.stream_to_s3 import stream_file_to_s3

WINDOWS = {
    "baseline": {"climate_scenario": "historical", "year_range": "2011_2014"},
    "future": {"climate_scenario": "ssp370", "year_range": "2051_2060"},
}


def fetch_climate_variable(variable: str, window: str, bucket: str, manifest_dir: Path) -> Path:
    """Stream one climate variable's decadal file for a given window into S3.

    Args: variable — "tas" or "pr". window — "baseline" or "future" (see WINDOWS).
        bucket — destination S3 bucket. manifest_dir — where to write the DVC-tracked manifest.
    Returns: path to the written manifest (the actual DVC stage output — see ADR-006 Step 8).
    """
    spec = WINDOWS[window]
    dataset = search_dataset(
        product="InputData",
        climate_scenario=spec["climate_scenario"],
        climate_variable=variable,
    )
    file_entry = file_for_year_range(dataset, spec["year_range"])

    key = f"raw/climate/{variable}/{file_entry['name']}"
    manifest = stream_file_to_s3(file_entry, bucket, key)
    return write_manifest(manifest, manifest_dir / f"{variable}_{window}.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variable", required=True, choices=["tas", "pr"])
    parser.add_argument("--window", required=True, choices=list(WINDOWS))
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--manifest-dir", required=True, type=Path)
    args = parser.parse_args()
    path = fetch_climate_variable(args.variable, args.window, args.bucket, args.manifest_dir)
    print(f"Wrote manifest: {path}")


if __name__ == "__main__":
    main()
