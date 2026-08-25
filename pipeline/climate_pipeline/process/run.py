"""Process stage entry point — turns fetched raw NetCDF into the real global precomputed grid.

Supersedes the earlier 5-fixed-point MVP. Regional extraction is explicitly out of scope here —
it stays a query-time concern (ADR-006 Step 3, the region vocabulary is unbounded) for whenever
the real API layer gets built. This stage's only job is to produce the global, per-(field,
window) change-from-baseline grids everything downstream will eventually read from.

Reads the local manifest files the fetch stages already wrote (dvc.yaml wires those as this
stage's deps). Downloads only the raw NetCDF each manifest points at — one hop, S3 to this
stage's own ephemeral compute (ADR-006 Step 8) — computes 67 years' worth of 20-year-window
change grids and writes each as its own small NetCDF object under
processed/global/{field}/y{year}.nc, plus a manifest listing all of them with their
{field, year, gwl_c} so a future consumer can find the right key without listing the S3 prefix.

Not every field gets one output — some get two. Percent change is only valid for continuous,
ratio-scale quantities with a true zero where it's the domain-conventional framing (pr, yield);
it's invalid for temperature (no true zero) and misleading for day-counts (near-zero baselines
are common and produce meaningless swings). Where percent is valid, both absolute and percent are
computed and stored — not one chosen on the data's behalf — because a small-baseline cell (arid
precip, marginal cropland) can make percent change technically correct but misleading, and this
project's convention is to let a downstream consumer see both rather than silently pick.
tas/consecutive_dry_days/extreme_heat_days get one output field each (bare name); pr and the 4
crops get two each (name_abs, name_pct) — see FIELD_VARIANTS. 3 single + 5 doubled = 13
field-variants x 67 windows = 871 objects (~871MB), up from the earlier 536.

Also writes gwl_year_table.json — the compact {gwl_c, year} lookup timecode() needs for a direct
table[gwl] -> year lookup (ADR-005's flagged gap: this used to only exist duplicated across the
871-entry field manifest, never as its own small artifact).

Whole-run skip-check: before downloading anything, hashes every input manifest's checksums into
one fingerprint (compute_input_fingerprint) and compares it against the fingerprint recorded on
the last successful run's processed/global/manifest.json (S3 object metadata, same convention
stream_to_s3.py already uses for its own per-file skip-check). Unlike fetch's per-file check, this
stage has no cheap unit smaller than "the whole run" to skip at — any single changed input forces
a full recompute, so the fingerprint covers all inputs at once rather than per-file.
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
from climate_pipeline.process.warming_levels import (
    VALID_CENTER_YEARS,
    gwl_for_year,
    preindustrial_reference,
    window_for_year,
)

BASELINE_START_YEAR = 1995
BASELINE_END_YEAR = 2014

CLIMATE_FIELDS = ["tas", "pr", "consecutive_dry_days", "extreme_heat_days"]
CROP_FIELDS = list(CROPS)
ALL_FIELDS = CLIMATE_FIELDS + CROP_FIELDS

# Which change-kind(s) each field gets — see module docstring for the reasoning. tas and the two
# day-count indices are absolute-only (percent is invalid or misleading for them, not just less
# useful — adding it would be actively wrong, not a missing nice-to-have). pr and yield get both.
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


EXPECTED_GRID_LAT = 360
EXPECTED_GRID_LON = 720


def _load_manifest(manifest_dir: Path, name: str) -> dict:
    return json.loads((manifest_dir / f"{name}.json").read_text())


def _manifest_checksums(manifest: dict) -> list[str]:
    """All raw-file checksums one fetch manifest covers. Climate manifests (climate.py) nest a
    list under "files"; agriculture manifests (agriculture.py) are a single stream_file_to_s3()
    result with the checksum at the top level. Both shapes feed the same fingerprint."""
    if "files" in manifest:
        return [f["checksum"] for f in manifest["files"]]
    return [manifest["checksum"]]


def compute_input_fingerprint(manifests: list[dict]) -> str:
    """One hash standing in for every raw input file this run depends on. Unchanged since the
    last successful run means the output would be byte-identical, so the whole run — including
    the ~56GB of downloads that precede any actual compute — can be skipped."""
    checksums = sorted(c for manifest in manifests for c in _manifest_checksums(manifest))
    return hashlib.sha256("|".join(checksums).encode("utf-8")).hexdigest()


def _existing_manifest_and_fingerprint(s3, bucket: str) -> tuple[dict, str] | None:
    """The previous successful run's manifest body and the input fingerprint it was recorded
    under, if a previous run exists at all. Mirrors stream_to_s3.py's own skip-check: tracking
    state lives in S3 object metadata, checked via head_object, not in DVC's own dvc.lock (which
    a fresh CodeBuild checkout won't reliably have)."""
    try:
        head = s3.head_object(Bucket=bucket, Key="processed/global/manifest.json")
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise

    fingerprint = head.get("Metadata", {}).get("input-fingerprint")
    if fingerprint is None:
        return None

    obj = s3.get_object(Bucket=bucket, Key="processed/global/manifest.json")
    return json.loads(obj["Body"].read()), fingerprint


def _download(s3, bucket: str, s3_key: str, dest_dir: Path) -> Path:
    dest = dest_dir / Path(s3_key).name
    if not dest.exists():
        s3.download_file(bucket, s3_key, str(dest))
    return dest


def _open_climate_dataset(s3, bucket: str, manifest: dict, work_dir: Path) -> xr.Dataset:
    paths = [_download(s3, bucket, f["s3_key"], work_dir) for f in manifest["files"]]
    return xr.open_mfdataset([str(p) for p in paths], combine="by_coords")


def _open_yield_dataset(s3, bucket: str, manifest: dict, work_dir: Path) -> xr.Dataset:
    """LPJmL's time coordinate is a season-index, not real calendar time (units like "growing
    seasons since 1601-01-01", calendar "360_day") — a real, now-confirmed case of the risk
    extract.py's module docstring flagged as unverified. xarray's default decode_times=True tries
    to CF-decode it anyway and fails before yield_season_start_year/yield_grid_mean ever run,
    since "growing seasons" isn't a real time unit cftime recognizes. decode_times=False leaves
    the raw numeric season index alone, which is exactly what those functions already expect."""
    path = _download(s3, bucket, manifest["s3_key"], work_dir)
    return xr.open_dataset(path, decode_times=False)


def _assert_grid_shape(dataset: xr.Dataset, variable: str) -> None:
    """LPJmL yield data is assumed to share the climate driver grid (720x360, 0.5deg) — ISIMIP's
    protocol mandates a common grid across sectors, and this session verified the variable-name
    convention live, but the actual array shape hasn't been directly inspected. Fail loudly here
    rather than silently misalign a global grid."""
    sizes = dataset[variable].sizes
    if sizes.get("lat") != EXPECTED_GRID_LAT or sizes.get("lon") != EXPECTED_GRID_LON:
        raise ValueError(
            f"{variable} grid shape {dict(sizes)} doesn't match expected "
            f"{{'lat': {EXPECTED_GRID_LAT}, 'lon': {EXPECTED_GRID_LON}}} — "
            "LPJmL/climate grid mismatch, investigate before trusting this run's output."
        )


def _write_field_window(
    field_da: xr.DataArray, output_field: str, kind: str, year: int, gwl_c: float, out_dir: Path
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"y{year}.nc"
    ds = field_da.rename(output_field).to_dataset()
    ds.attrs["year"] = year
    ds.attrs["gwl_c"] = round(gwl_c, 3)
    ds.attrs["change_kind"] = kind
    # No explicit engine — same default (netCDF4, already a real production dependency) as
    # every open_dataset/open_mfdataset call elsewhere in this pipeline. h5netcdf is dev-only,
    # used by the separate storage-format benchmark, not this production path.
    ds.to_netcdf(path)
    return path


def process_global(bucket: str, manifest_dir: Path, work_dir: Path, out_dir: Path) -> dict:
    s3 = boto3.client("s3")
    work_dir.mkdir(parents=True, exist_ok=True)

    tas_preindustrial_manifest = _load_manifest(manifest_dir, "tas_preindustrial")
    tas_baseline_manifest = _load_manifest(manifest_dir, "tas_baseline")
    pr_baseline_manifest = _load_manifest(manifest_dir, "pr_baseline")
    tas_future_manifest = _load_manifest(manifest_dir, "tas_future")
    pr_future_manifest = _load_manifest(manifest_dir, "pr_future")
    yield_baseline_manifests = {c: _load_manifest(manifest_dir, f"lpjml_{c}_baseline") for c in CROPS}
    yield_future_manifests = {c: _load_manifest(manifest_dir, f"lpjml_{c}_future") for c in CROPS}

    input_manifests = [
        tas_preindustrial_manifest,
        tas_baseline_manifest,
        pr_baseline_manifest,
        tas_future_manifest,
        pr_future_manifest,
        *yield_baseline_manifests.values(),
        *yield_future_manifests.values(),
    ]
    fingerprint = compute_input_fingerprint(input_manifests)

    existing = _existing_manifest_and_fingerprint(s3, bucket)
    if existing is not None and existing[1] == fingerprint:
        existing_manifest, _ = existing
        print(
            f"Input fingerprint unchanged ({fingerprint[:12]}...) — all raw inputs match the "
            "last successful run, skipping download and recompute entirely."
        )
        return {**existing_manifest, "skipped": True, "input_fingerprint": fingerprint}

    tas_preindustrial_ds = _open_climate_dataset(s3, bucket, tas_preindustrial_manifest, work_dir)
    tas_baseline_ds = _open_climate_dataset(s3, bucket, tas_baseline_manifest, work_dir)
    pr_baseline_ds = _open_climate_dataset(s3, bucket, pr_baseline_manifest, work_dir)
    tas_future_ds = _open_climate_dataset(s3, bucket, tas_future_manifest, work_dir)
    pr_future_ds = _open_climate_dataset(s3, bucket, pr_future_manifest, work_dir)
    yield_baseline_ds = {c: _open_yield_dataset(s3, bucket, yield_baseline_manifests[c], work_dir) for c in CROPS}
    yield_future_ds = {c: _open_yield_dataset(s3, bucket, yield_future_manifests[c], work_dir) for c in CROPS}

    for c in CROPS:
        _assert_grid_shape(yield_baseline_ds[c], f"yield-{CROPS[c]}-noirr")

    preindustrial_ref = preindustrial_reference(tas_preindustrial_ds)

    baseline_grids = {
        "tas": grid_mean(tas_baseline_ds, "tas", BASELINE_START_YEAR, BASELINE_END_YEAR),
        "pr": grid_mean(pr_baseline_ds, "pr", BASELINE_START_YEAR, BASELINE_END_YEAR),
    }
    baseline_grids["consecutive_dry_days"] = (
        consecutive_dry_days_per_year(pr_baseline_ds)
        .sel(year=slice(BASELINE_START_YEAR, BASELINE_END_YEAR))
        .mean(dim="year")
    )
    baseline_grids["extreme_heat_days"] = (
        extreme_heat_days_per_year(tas_baseline_ds)
        .sel(year=slice(BASELINE_START_YEAR, BASELINE_END_YEAR))
        .mean(dim="year")
    )
    for crop in CROPS:
        baseline_grids[crop] = yield_grid_mean(
            yield_baseline_ds[crop], f"yield-{CROPS[crop]}-noirr", BASELINE_START_YEAR, BASELINE_END_YEAR
        )

    future_dry_days_years = consecutive_dry_days_per_year(pr_future_ds)
    future_heat_days_years = extreme_heat_days_per_year(tas_future_ds)

    manifest_entries = []
    gwl_year_table = []
    for year in VALID_CENTER_YEARS:
        start_year, end_year = window_for_year(year)
        gwl_c = gwl_for_year(tas_future_ds, year, preindustrial_ref)
        gwl_year_table.append({"gwl_c": round(gwl_c, 3), "year": year})

        window_grids = {
            "tas": grid_mean(tas_future_ds, "tas", start_year, end_year),
            "pr": grid_mean(pr_future_ds, "pr", start_year, end_year),
            "consecutive_dry_days": future_dry_days_years.sel(year=slice(start_year, end_year)).mean(dim="year"),
            "extreme_heat_days": future_heat_days_years.sel(year=slice(start_year, end_year)).mean(dim="year"),
        }
        for crop in CROPS:
            window_grids[crop] = yield_grid_mean(
                yield_future_ds[crop], f"yield-{CROPS[crop]}-noirr", start_year, end_year
            )

        for field in ALL_FIELDS:
            for kind in FIELD_VARIANTS[field]:
                change = (
                    absolute_change(window_grids[field], baseline_grids[field])
                    if kind == "absolute"
                    else percent_change_grid(window_grids[field], baseline_grids[field])
                )

                output_field = output_field_name(field, kind)
                path = _write_field_window(change, output_field, kind, year, gwl_c, out_dir / output_field)
                key = f"processed/global/{output_field}/y{year}.nc"
                s3.upload_file(str(path), bucket, key)
                manifest_entries.append(
                    {"field": output_field, "kind": kind, "year": year, "gwl_c": round(gwl_c, 3), "s3_key": key}
                )

    return {
        "fields": manifest_entries,
        "gwl_year_table": sorted(gwl_year_table, key=lambda entry: entry["gwl_c"]),
        "provenance": {
            "climate_model": "GFDL-ESM4",
            "scenario": "SSP3-7.0",
            "crop_model": "LPJmL",
            "baseline_start_year": BASELINE_START_YEAR,
            "baseline_end_year": BASELINE_END_YEAR,
            "preindustrial_reference_tas_k": round(preindustrial_ref, 4),
            "processed_at": datetime.now(UTC).isoformat(),
        },
        "skipped": False,
        "input_fingerprint": fingerprint,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--manifest-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    output = process_global(args.bucket, args.manifest_dir, args.work_dir, args.out_dir)

    # Written every run, skipped or not — DVC needs its declared outs to exist, and on a skip
    # they're identical to the last successful run's (that's the point of the fingerprint match).
    out_path = write_manifest(output, args.manifest_dir / "global_precompute_manifest.json")
    gwl_table_path = write_manifest(
        {"gwl_year_table": output["gwl_year_table"]}, args.manifest_dir / "gwl_year_table.json"
    )

    if output["skipped"]:
        print(f"Skipped — wrote {out_path} and {gwl_table_path} from the last successful run, nothing new to upload.")
        return

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=args.bucket,
        Key="processed/global/manifest.json",
        Body=json.dumps(output, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
        # Read back by _existing_manifest_and_fingerprint() on the next run to decide whether to
        # skip — same "state lives in S3 object metadata" convention stream_to_s3.py already uses.
        Metadata={"input-fingerprint": output["input_fingerprint"]},
    )
    # timecode()'s dedicated artifact (ADR-005's flagged gap): the one compact gwl->year object a
    # direct lookup needs, not the 871-entry field manifest every consumer would otherwise have to
    # scan.
    s3.put_object(
        Bucket=args.bucket,
        Key="processed/global/gwl_year_table.json",
        Body=json.dumps(output["gwl_year_table"], sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )

    print(
        f"Wrote {out_path}, {gwl_table_path}, s3://{args.bucket}/processed/global/manifest.json, and "
        f"s3://{args.bucket}/processed/global/gwl_year_table.json ({len(output['fields'])} fields, "
        f"{len(output['gwl_year_table'])} gwl_year_table entries)"
    )


if __name__ == "__main__":
    main()
