"""Process stage entry point — turns fetched raw NetCDF into real per-region values for the
frontend's 5 known demo regions (see regions.py, warming_levels.py, extract.py).

Reads the local manifest files the fetch stages already wrote: dvc.yaml wires those as this
stage's deps, so `dvc repro` guarantees they're present on disk before this runs — no need to
re-derive S3 keys from anywhere else. Downloads only the raw NetCDF each manifest points at (one
hop, S3 to this stage's own ephemeral compute — see ADR-006 Step 8), extracts values for all 5
regions, and writes the result twice: once as this stage's own small DVC-tracked output
(manifests/processed_regions.json — no manifest-indirection needed here, unlike fetch, since this
payload is already small; see ADR-006 Step 8's reasoning for why that indirection existed at all),
and once uploaded directly to s3://{bucket}/processed/regions.json, which is what CloudFront
actually serves to the frontend (see infra/stacks/frontend_hosting_stack.py).
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import boto3
import xarray as xr

from climate_pipeline.fetch.agriculture import CROPS
from climate_pipeline.fetch.manifest import write_manifest
from climate_pipeline.process.extract import (
    absolute_change,
    nearest_point_mean,
    nearest_point_yield_mean,
    percent_change,
)
from climate_pipeline.process.regions import REGIONS
from climate_pipeline.process.warming_levels import WARMING_LEVEL_CENTER_YEARS, window_for_gwl

BASELINE_START_YEAR = 1995
BASELINE_END_YEAR = 2014

CLIMATE_VARIABLES = ["tas", "pr"]
# Absolute change (temp) vs. percent change (precip) — see README's "always report what the data
# supports" convention; a percent change on a near-zero baseline temperature would be meaningless,
# and an absolute change on precipitation wouldn't be comparable across regions of different
# baseline wetness.
CLIMATE_CHANGE_KIND = {"tas": "absolute", "pr": "percent"}


def _load_manifest(manifest_dir: Path, name: str) -> dict:
    return json.loads((manifest_dir / f"{name}.json").read_text())


def _download(s3, bucket: str, s3_key: str, dest_dir: Path) -> Path:
    dest = dest_dir / Path(s3_key).name
    if not dest.exists():
        s3.download_file(bucket, s3_key, str(dest))
    return dest


def _open_climate_dataset(s3, bucket: str, manifest: dict, work_dir: Path) -> xr.Dataset:
    paths = [_download(s3, bucket, f["s3_key"], work_dir) for f in manifest["files"]]
    return xr.open_mfdataset([str(p) for p in paths], combine="by_coords")


def process_regions(bucket: str, manifest_dir: Path, work_dir: Path) -> dict:
    s3 = boto3.client("s3")
    work_dir.mkdir(parents=True, exist_ok=True)

    climate_baseline_manifests = {v: _load_manifest(manifest_dir, f"{v}_baseline") for v in CLIMATE_VARIABLES}
    climate_future_manifests = {v: _load_manifest(manifest_dir, f"{v}_future") for v in CLIMATE_VARIABLES}
    yield_baseline_manifests = {c: _load_manifest(manifest_dir, f"lpjml_{c}_baseline") for c in CROPS}
    yield_future_manifests = {c: _load_manifest(manifest_dir, f"lpjml_{c}_future") for c in CROPS}

    climate_baseline_ds = {
        v: _open_climate_dataset(s3, bucket, climate_baseline_manifests[v], work_dir) for v in CLIMATE_VARIABLES
    }
    climate_future_ds = {
        v: _open_climate_dataset(s3, bucket, climate_future_manifests[v], work_dir) for v in CLIMATE_VARIABLES
    }
    yield_baseline_ds = {
        c: xr.open_dataset(_download(s3, bucket, yield_baseline_manifests[c]["s3_key"], work_dir)) for c in CROPS
    }
    yield_future_ds = {
        c: xr.open_dataset(_download(s3, bucket, yield_future_manifests[c]["s3_key"], work_dir)) for c in CROPS
    }

    regions_out = {}
    for slug, region in REGIONS.items():
        lon, lat = region["lon"], region["lat"]

        climate_baseline_means = {
            v: nearest_point_mean(climate_baseline_ds[v], v, lon, lat, BASELINE_START_YEAR, BASELINE_END_YEAR)
            for v in CLIMATE_VARIABLES
        }
        yield_baseline_means = {
            c: nearest_point_yield_mean(
                yield_baseline_ds[c], f"yield-{CROPS[c]}-noirr", lon, lat, BASELINE_START_YEAR, BASELINE_END_YEAR
            )
            for c in CROPS
        }

        windows = []
        for gwl_c, center_year in WARMING_LEVEL_CENTER_YEARS.items():
            start_year, end_year = window_for_gwl(gwl_c)
            entry: dict = {"gwl_c": gwl_c, "center_year": center_year}

            for v in CLIMATE_VARIABLES:
                future_mean = nearest_point_mean(climate_future_ds[v], v, lon, lat, start_year, end_year)
                change = (
                    absolute_change(future_mean, climate_baseline_means[v])
                    if CLIMATE_CHANGE_KIND[v] == "absolute"
                    else percent_change(future_mean, climate_baseline_means[v])
                )
                entry[f"{v}_change"] = round(change, 3)

            for c in CROPS:
                future_mean = nearest_point_yield_mean(
                    yield_future_ds[c], f"yield-{CROPS[c]}-noirr", lon, lat, start_year, end_year
                )
                entry[f"{c}_yield_change_pct"] = round(
                    percent_change(future_mean, yield_baseline_means[c]), 2
                )

            windows.append(entry)

        regions_out[slug] = {"name": region["name"], "lon": lon, "lat": lat, "windows": windows}

    return {
        "regions": regions_out,
        "provenance": {
            "climate_model": "GFDL-ESM4",
            "scenario": "SSP3-7.0",
            "crop_model": "LPJmL",
            "baseline_start_year": BASELINE_START_YEAR,
            "baseline_end_year": BASELINE_END_YEAR,
            "processed_at": datetime.now(UTC).isoformat(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--manifest-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()

    output = process_regions(args.bucket, args.manifest_dir, args.work_dir)

    out_path = write_manifest(output, args.manifest_dir / "processed_regions.json")

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=args.bucket,
        Key="processed/regions.json",
        Body=json.dumps(output, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )

    print(f"Wrote {out_path} and s3://{args.bucket}/processed/regions.json")


if __name__ == "__main__":
    main()
