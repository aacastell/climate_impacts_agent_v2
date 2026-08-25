"""Computes and uploads gwl_year_table.json — the one artifact timecode() needs: table[gwl] ->
year (ADR-005). Derived from tas alone (preindustrial + future), and only from tas. This is fully
independent of every other process field: pr, maize, and every other field's own window statistic
is keyed purely by year, computed and stored with zero knowledge of what warming level that year
corresponds to. GWL enters the picture only at query time, when timecode() maps a requested
warming level to a year before looking up that year's already-computed field data.

An earlier version of this pipeline attached gwl_c as metadata to every field's own output
windows, and made every field's process depend on this table — a real, unforced mistake, not a
necessary design: pr and maize have no reason to know or care about global warming level at all.
Fixed by pulling this out into its own dedicated step.
"""

import argparse
import json
from pathlib import Path

import boto3
import xarray as xr
from botocore.exceptions import ClientError

from climate_pipeline.fetch.manifest import write_manifest
from climate_pipeline.process.warming_levels import VALID_CENTER_YEARS, gwl_for_year, preindustrial_reference


def _download(s3, bucket: str, key: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(dest))
    return dest


def _load_manifest(s3, bucket: str, manifest_dir: Path, name: str) -> dict:
    dest = manifest_dir / f"{name}.json"
    _download(s3, bucket, f"manifests/{name}.json", dest)
    return json.loads(dest.read_text())


def _open_climate_dataset(s3, bucket: str, manifest: dict, work_dir: Path) -> xr.Dataset:
    paths = [_download(s3, bucket, f["s3_key"], work_dir / Path(f["s3_key"]).name) for f in manifest["files"]]
    return xr.open_mfdataset([str(p) for p in paths], combine="by_coords")


def gwl_year_table_exists(s3, bucket: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key="processed/global/gwl_year_table.json")
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def compute_gwl_year_table(s3, bucket: str, manifest_dir: Path, work_dir: Path) -> list[dict]:
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    if gwl_year_table_exists(s3, bucket):
        print("Input unchanged (tas-derived, no per-run fingerprint needed) — skipping.")
        obj = s3.get_object(Bucket=bucket, Key="processed/global/gwl_year_table.json")
        return json.loads(obj["Body"].read())

    tas_preindustrial_manifest = _load_manifest(s3, bucket, manifest_dir, "tas_preindustrial")
    tas_future_manifest = _load_manifest(s3, bucket, manifest_dir, "tas_future")
    tas_preindustrial_ds = _open_climate_dataset(s3, bucket, tas_preindustrial_manifest, work_dir)
    tas_future_ds = _open_climate_dataset(s3, bucket, tas_future_manifest, work_dir)

    preindustrial_ref = preindustrial_reference(tas_preindustrial_ds)
    gwl_year_table = sorted(
        (
            {"gwl_c": round(gwl_for_year(tas_future_ds, year, preindustrial_ref), 3), "year": year}
            for year in VALID_CENTER_YEARS
        ),
        key=lambda entry: entry["gwl_c"],
    )

    s3.put_object(
        Bucket=bucket,
        Key="processed/global/gwl_year_table.json",
        Body=json.dumps(gwl_year_table, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )
    write_manifest(gwl_year_table, manifest_dir / "gwl_year_table.json")
    return gwl_year_table


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--manifest-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()

    table = compute_gwl_year_table(boto3.client("s3"), args.bucket, args.manifest_dir, args.work_dir)
    print(f"Wrote {len(table)} gwl_year_table entries to s3://{args.bucket}/processed/global/gwl_year_table.json")


if __name__ == "__main__":
    main()
