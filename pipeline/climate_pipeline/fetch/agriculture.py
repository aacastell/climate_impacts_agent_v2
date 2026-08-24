"""Fetches ISIMIP crop yield data for one window, streaming straight to S3.

Scope: LPJmL maize (noirr, 2015soc) only, for now — matching the crop and run
specifier the root README already commits to. pDSSAT (the second crop model
the README's "report the range, never a mean" convention needs) and the other
three crops (spring wheat, soy, rice) are follow-up scope, not omitted silently.
"""

import argparse
from pathlib import Path

from climate_pipeline.fetch.isimip_client import only_file, search_dataset
from climate_pipeline.fetch.manifest import write_manifest
from climate_pipeline.fetch.stream_to_s3 import stream_file_to_s3

WINDOWS = {"baseline": "historical", "future": "ssp370"}
SENS_SCENARIO = {"baseline": "default", "future": "2015co2"}


def fetch_agriculture(window: str, bucket: str, manifest_dir: Path) -> Path:
    """Stream the maize yield dataset (LPJmL, rainfed) for a given window into S3.

    Args: window — "baseline" or "future" (see WINDOWS). bucket — destination S3 bucket.
        manifest_dir — where to write the DVC-tracked manifest.
    Returns: path to the written manifest (the actual DVC stage output — see ADR-006 Step 8).
    """
    dataset = search_dataset(
        product="OutputData",
        sector="agriculture",
        model="lpjml",
        crop="mai",
        variable="yield",
        irrigation="noirr",
        soc_scenario="2015soc",
        sens_scenario=SENS_SCENARIO[window],
        climate_scenario=WINDOWS[window],
    )
    file_entry = only_file(dataset)

    key = f"raw/agriculture/lpjml_maize/{file_entry['name']}"
    manifest = stream_file_to_s3(file_entry, bucket, key)
    return write_manifest(manifest, manifest_dir / f"lpjml_maize_{window}.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", required=True, choices=list(WINDOWS))
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--manifest-dir", required=True, type=Path)
    args = parser.parse_args()
    path = fetch_agriculture(args.window, args.bucket, args.manifest_dir)
    print(f"Wrote manifest: {path}")


if __name__ == "__main__":
    main()
