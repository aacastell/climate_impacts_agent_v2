"""Process stage — one independent unit per field, not one monolithic run.

Each field (tas, pr, consecutive_dry_days, extreme_heat_days, maize, spring_wheat, soy, rice) is
processed by its own invocation of this module (--field), needing only that field's own two fetch
manifests as real input, downloaded directly from a fixed S3 key (see
fetch/manifest.py's upload_manifest) — no `dvc repro`, no dependency-graph traversal, no
possibility of one field's build touching another's work.

This replaces an earlier monolithic process_global() that computed all 8 fields' 67-year windows
in one process. Real profiling data (a CodeBuild TIMED_OUT after ~41 minutes of silent execution,
having already burned through the account's ~45-minute cap) showed that didn't fit, and routing
every stage through `dvc repro <target>` caused real, unwanted coupling: since dvc.lock is never
committed to git, a fresh CodeBuild checkout has no record of what fetch already did, so `dvc
repro process_global` re-executed the entire upstream fetch graph every single time, regardless of
which target was asked for.

No field here knows or cares about global warming level. Each field's own output windows are keyed
purely by year — GWL is resolved separately (see gwl_table.py), only at query time, when
timecode() maps a requested warming level to a year before this field data ever gets looked up. An
earlier version attached gwl_c metadata to every field's own output and made every field depend on
computing it — a real, unforced mistake (pr and maize have no reason to know about tas-derived
warming levels at all), fixed by pulling that into its own independent step.

Not every field gets one output — some get two. Percent change is only valid for continuous,
ratio-scale quantities with a true zero where it's the domain-conventional framing (pr, yield);
it's invalid for temperature (no true zero) and misleading for day-counts (near-zero baselines are
common and produce meaningless swings). Where percent is valid, both absolute and percent are
computed and stored — see FIELD_VARIANTS.
"""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import boto3
import xarray as xr
from botocore.exceptions import ClientError

from climate_pipeline.fetch.agriculture import CROPS
from climate_pipeline.fetch.manifest import write_manifest
from climate_pipeline.process.extract import (
    absolute_change,
    grid_mean,
    percent_change_grid,
    yield_grid_mean,
)
from climate_pipeline.process.indices import (
    consecutive_dry_days_per_year,
    extreme_heat_days_per_year,
)
from climate_pipeline.process.warming_levels import VALID_CENTER_YEARS, window_for_year

BASELINE_START_YEAR = 1995
BASELINE_END_YEAR = 2014

CLIMATE_FIELDS = ["tas", "pr", "consecutive_dry_days", "extreme_heat_days"]
CROP_FIELDS = list(CROPS)
ALL_FIELDS = CLIMATE_FIELDS + CROP_FIELDS

# Which change-kind(s) each field gets — see module docstring for the reasoning.
FIELD_VARIANTS = {
    "tas": ["absolute"],
    "pr": ["absolute", "percent"],
    "consecutive_dry_days": ["absolute"],
    "extreme_heat_days": ["absolute"],
    **{crop: ["absolute", "percent"] for crop in CROP_FIELDS},
}

# The exact two fetch manifests each field needs — its own real data dependency, nothing more.
# consecutive_dry_days/extreme_heat_days are derived indices but still only ever touch pr/tas
# respectively, same as the base climate fields they're derived from.
FIELD_MANIFESTS = {
    "tas": ("tas_baseline", "tas_future"),
    "pr": ("pr_baseline", "pr_future"),
    "consecutive_dry_days": ("pr_baseline", "pr_future"),
    "extreme_heat_days": ("tas_baseline", "tas_future"),
    **{crop: (f"lpjml_{crop}_baseline", f"lpjml_{crop}_future") for crop in CROP_FIELDS},
}

EXPECTED_GRID_LAT = 360
EXPECTED_GRID_LON = 720


def output_field_name(base_field: str, kind: str) -> str:
    variants = FIELD_VARIANTS[base_field]
    if len(variants) == 1:
        return base_field
    return f"{base_field}_{'abs' if kind == 'absolute' else 'pct'}"


def _download(s3, bucket: str, key: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(dest))
    return dest


def _load_manifest(s3, bucket: str, manifest_dir: Path, name: str) -> dict:
    """Downloads a fetch manifest directly from its fixed S3 key — no dvc repro involved. Fails
    loudly (real S3 error) if the fetch stage this field depends on hasn't actually run yet."""
    dest = manifest_dir / f"{name}.json"
    _download(s3, bucket, f"manifests/{name}.json", dest)
    return json.loads(dest.read_text())


def _manifest_checksums(manifest: dict) -> list[str]:
    """All raw-file checksums one fetch manifest covers. Climate manifests nest a list under
    "files"; agriculture manifests are a single stream_file_to_s3() result with the checksum at
    the top level."""
    if "files" in manifest:
        return [f["checksum"] for f in manifest["files"]]
    return [manifest["checksum"]]


def compute_input_fingerprint(manifests: list[dict]) -> str:
    """One hash standing in for every raw input file this field's run depends on. Unchanged since
    the last successful run means the output would be byte-identical, so this field's whole run
    can be skipped."""
    checksums = sorted(c for manifest in manifests for c in _manifest_checksums(manifest))
    return hashlib.sha256("|".join(checksums).encode("utf-8")).hexdigest()


def _head_json(s3, bucket: str, key: str) -> tuple[dict, str] | None:
    """The object's body plus its recorded input-fingerprint metadata, or None if it doesn't
    exist yet."""
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise
    fingerprint = head.get("Metadata", {}).get("input-fingerprint")
    obj = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read()), fingerprint


def _open_climate_dataset(s3, bucket: str, manifest: dict, work_dir: Path) -> xr.Dataset:
    paths = [_download(s3, bucket, f["s3_key"], work_dir / Path(f["s3_key"]).name) for f in manifest["files"]]
    return xr.open_mfdataset([str(p) for p in paths], combine="by_coords")


def _open_yield_dataset(s3, bucket: str, manifest: dict, work_dir: Path) -> xr.Dataset:
    """LPJmL's time coordinate is a season-index, not real calendar time (units like "growing
    seasons since 1601-01-01", calendar "360_day") — decode_times=False leaves the raw numeric
    season index alone, which is what extract.py's yield functions expect."""
    path = _download(s3, bucket, manifest["s3_key"], work_dir / Path(manifest["s3_key"]).name)
    return xr.open_dataset(path, decode_times=False)


def _assert_grid_shape(dataset: xr.Dataset, variable: str) -> None:
    sizes = dataset[variable].sizes
    if sizes.get("lat") != EXPECTED_GRID_LAT or sizes.get("lon") != EXPECTED_GRID_LON:
        raise ValueError(
            f"{variable} grid shape {dict(sizes)} doesn't match expected "
            f"{{'lat': {EXPECTED_GRID_LAT}, 'lon': {EXPECTED_GRID_LON}}} — "
            "LPJmL/climate grid mismatch, investigate before trusting this run's output."
        )


def _write_field_window(field_da: xr.DataArray, output_field: str, kind: str, year: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"y{year}.nc"
    ds = field_da.rename(output_field).to_dataset()
    ds.attrs["year"] = year
    ds.attrs["change_kind"] = kind
    ds.to_netcdf(path)
    return path


def _load_field_data(s3, bucket: str, field: str, baseline_manifest: dict, future_manifest: dict, work_dir: Path):
    """Returns (baseline_grid, future_window_fn) for one field — future_window_fn(start_year,
    end_year) -> xr.DataArray, the per-cell mean over that window."""
    if field in CROP_FIELDS:
        baseline_ds = _open_yield_dataset(s3, bucket, baseline_manifest, work_dir)
        future_ds = _open_yield_dataset(s3, bucket, future_manifest, work_dir)
        variable = f"yield-{CROPS[field]}-noirr"
        _assert_grid_shape(baseline_ds, variable)
        baseline_grid = yield_grid_mean(baseline_ds, variable, BASELINE_START_YEAR, BASELINE_END_YEAR)
        return baseline_grid, lambda s, e: yield_grid_mean(future_ds, variable, s, e)

    if field in ("tas", "pr"):
        baseline_ds = _open_climate_dataset(s3, bucket, baseline_manifest, work_dir)
        future_ds = _open_climate_dataset(s3, bucket, future_manifest, work_dir)
        baseline_grid = grid_mean(baseline_ds, field, BASELINE_START_YEAR, BASELINE_END_YEAR)
        return baseline_grid, lambda s, e: grid_mean(future_ds, field, s, e)

    if field == "consecutive_dry_days":
        baseline_ds = _open_climate_dataset(s3, bucket, baseline_manifest, work_dir)
        future_ds = _open_climate_dataset(s3, bucket, future_manifest, work_dir)
        baseline_years = consecutive_dry_days_per_year(baseline_ds)
        baseline_grid = baseline_years.sel(year=slice(BASELINE_START_YEAR, BASELINE_END_YEAR)).mean(dim="year")
        future_years = consecutive_dry_days_per_year(future_ds)
        return baseline_grid, lambda s, e: future_years.sel(year=slice(s, e)).mean(dim="year")

    if field == "extreme_heat_days":
        baseline_ds = _open_climate_dataset(s3, bucket, baseline_manifest, work_dir)
        future_ds = _open_climate_dataset(s3, bucket, future_manifest, work_dir)
        baseline_years = extreme_heat_days_per_year(baseline_ds)
        baseline_grid = baseline_years.sel(year=slice(BASELINE_START_YEAR, BASELINE_END_YEAR)).mean(dim="year")
        future_years = extreme_heat_days_per_year(future_ds)
        return baseline_grid, lambda s, e: future_years.sel(year=slice(s, e)).mean(dim="year")

    raise ValueError(f"Unknown field {field!r}")


def process_field(bucket: str, manifest_dir: Path, work_dir: Path, out_dir: Path, field: str) -> dict:
    s3 = boto3.client("s3")
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    baseline_name, future_name = FIELD_MANIFESTS[field]
    baseline_manifest = _load_manifest(s3, bucket, manifest_dir, baseline_name)
    future_manifest = _load_manifest(s3, bucket, manifest_dir, future_name)
    fingerprint = compute_input_fingerprint([baseline_manifest, future_manifest])

    manifest_key = f"processed/global/_manifests/{field}.json"
    existing = _head_json(s3, bucket, manifest_key)
    if existing is not None and existing[1] == fingerprint:
        existing_manifest, _ = existing
        print(f"[{field}] Input fingerprint unchanged ({fingerprint[:12]}...) — skipping.")
        return {**existing_manifest, "skipped": True, "input_fingerprint": fingerprint}

    baseline_grid, future_window = _load_field_data(s3, bucket, field, baseline_manifest, future_manifest, work_dir)

    manifest_entries = []
    for year in VALID_CENTER_YEARS:
        start_year, end_year = window_for_year(year)
        window_grid = future_window(start_year, end_year)

        for kind in FIELD_VARIANTS[field]:
            change = (
                absolute_change(window_grid, baseline_grid)
                if kind == "absolute"
                else percent_change_grid(window_grid, baseline_grid)
            )
            output_field = output_field_name(field, kind)
            path = _write_field_window(change, output_field, kind, year, out_dir / output_field)
            key = f"processed/global/{output_field}/y{year}.nc"
            s3.upload_file(str(path), bucket, key)
            manifest_entries.append({"field": output_field, "kind": kind, "year": year, "s3_key": key})

    output = {
        "field": field,
        "entries": manifest_entries,
        "provenance": {
            "climate_model": "GFDL-ESM4",
            "scenario": "SSP3-7.0",
            "crop_model": "LPJmL",
            "baseline_start_year": BASELINE_START_YEAR,
            "baseline_end_year": BASELINE_END_YEAR,
            "processed_at": datetime.now(UTC).isoformat(),
        },
        "skipped": False,
        "input_fingerprint": fingerprint,
    }

    s3.put_object(
        Bucket=bucket,
        Key=manifest_key,
        Body=json.dumps(output, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
        Metadata={"input-fingerprint": fingerprint},
    )
    write_manifest(output, manifest_dir / f"{field}_manifest.json")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--field", required=True, choices=ALL_FIELDS)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--manifest-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    output = process_field(args.bucket, args.manifest_dir, args.work_dir, args.out_dir, args.field)

    if output["skipped"]:
        print(f"[{args.field}] Skipped — inputs unchanged since the last successful run.")
    else:
        print(f"[{args.field}] Wrote {len(output['entries'])} field-windows to s3://{args.bucket}/processed/global/")


if __name__ == "__main__":
    main()
