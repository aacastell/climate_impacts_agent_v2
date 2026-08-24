"""Fetches an ISIMIP climate driver variable's baseline or future window,
streaming each covering file straight to S3.

Scope: temperature (tas) and precipitation (pr) only, for now — matching the two
climate drivers already wired into the frontend's mock indicators. Extreme-heat-day
and dry-day counts are derived indicators, not raw ISIMIP variables fetched directly;
how they get computed belongs to the process stage, not fetch.

Baseline: 1995-2014, the last 20 years of ISIMIP's historical record (the
only period ending where the historical data actually ends). Future:
2026-2100. ISIMIP only serves whole pre-chunked decadal files, not
arbitrary date ranges (verified directly against the catalog), so a target
window that doesn't align with ISIMIP's own chunk boundaries still means
fetching whole files that cover it — a few extra years ride along in a
boundary-straddling file, trimmed later in the process stage, never here.
"""

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

from climate_pipeline.fetch.isimip_client import search_dataset
from climate_pipeline.fetch.manifest import write_manifest
from climate_pipeline.fetch.profiling import record_run
from climate_pipeline.fetch.stream_to_s3 import stream_file_to_s3

WINDOWS = {
    "baseline": {"climate_scenario": "historical", "start_year": 1995, "end_year": 2014},
    "future": {"climate_scenario": "ssp370", "start_year": 2026, "end_year": 2100},
}

_YEAR_RANGE_RE = re.compile(r"_(\d{4})_(\d{4})\.nc$")


def _files_overlapping(files: list[dict], start_year: int, end_year: int) -> list[dict]:
    """Every file whose own year range (parsed from its filename) overlaps
    [start_year, end_year] — see module docstring on why this is whole
    covering files, not an exact trim to the target range."""
    matched = []
    for file_entry in files:
        match = _YEAR_RANGE_RE.search(file_entry["name"])
        if not match:
            raise ValueError(f"Could not parse a year range from {file_entry['name']}")
        file_start, file_end = int(match.group(1)), int(match.group(2))
        if file_start <= end_year and file_end >= start_year:
            matched.append(file_entry)
    return matched


def fetch_climate_variable(variable: str, window: str, bucket: str, manifest_dir: Path) -> Path:
    """Stream every file covering one climate variable's target window into S3.

    Args: variable — "tas" or "pr". window — "baseline" or "future" (see WINDOWS).
        bucket — destination S3 bucket. manifest_dir — where to write the DVC-tracked manifest.
    Returns: path to the written manifest (the actual DVC stage output — see ADR-006 Step 8).
    """
    started_at = datetime.now(UTC)
    spec = WINDOWS[window]
    dataset = search_dataset(
        product="InputData",
        climate_scenario=spec["climate_scenario"],
        climate_variable=variable,
    )
    files = _files_overlapping(dataset["files"], spec["start_year"], spec["end_year"])

    file_manifests = [
        stream_file_to_s3(
            file_entry, bucket, f"raw/climate/{variable}/{spec['climate_scenario']}/{file_entry['name']}"
        )
        for file_entry in files
    ]

    record_run(bucket, f"{variable}_{window}", started_at, file_manifests)

    return write_manifest(
        {
            "variable": variable,
            "scenario": spec["climate_scenario"],
            "target_start_year": spec["start_year"],
            "target_end_year": spec["end_year"],
            "files": file_manifests,
        },
        manifest_dir / f"{variable}_{window}.json",
    )


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
