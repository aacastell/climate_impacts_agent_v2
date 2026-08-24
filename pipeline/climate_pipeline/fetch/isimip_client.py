"""Queries ISIMIP's public dataset API for file metadata.

No auth: ISIMIP's data is CC0 public domain, served from a public,
unauthenticated REST API (verified directly against data.isimip.org — see
ADR-006). This module only resolves *which* file to fetch and its
metadata (URL, checksum, size); it never downloads file content itself —
see stream_to_s3.py for that.
"""

import httpx

ISIMIP_API_BASE = "https://data.isimip.org/api/v1"
DEFAULT_SIMULATION_ROUND = "ISIMIP3b"
DEFAULT_CLIMATE_FORCING = "gfdl-esm4"


def search_dataset(**specifiers) -> dict:
    """Search ISIMIP for a single dataset matching the given specifiers, fixed to this project's model.

    Args: specifiers — ISIMIP API query params (e.g. climate_scenario="ssp370", sector="agriculture").
    Returns: the first matching dataset's full detail, including its files list.
    """
    params = {
        "simulation_round": DEFAULT_SIMULATION_ROUND,
        "climate_forcing": DEFAULT_CLIMATE_FORCING,
        "page_size": 1,
        **specifiers,
    }
    search = httpx.get(f"{ISIMIP_API_BASE}/datasets/", params=params, timeout=30.0)
    search.raise_for_status()
    results = search.json()["results"]
    if not results:
        raise ValueError(f"No ISIMIP dataset found for {specifiers}")

    detail = httpx.get(f"{ISIMIP_API_BASE}/datasets/{results[0]['id']}/", timeout=30.0)
    detail.raise_for_status()
    return detail.json()


def file_for_year_range(dataset: dict, year_range: str) -> dict:
    """Pick the file within a dataset matching a year-range suffix in its filename (e.g. "2051_2060")."""
    for file_entry in dataset["files"]:
        if year_range in file_entry["name"]:
            return file_entry
    raise ValueError(f"No file matching {year_range} in dataset {dataset['id']}")


def only_file(dataset: dict) -> dict:
    """A dataset's single file, for sectors whose output isn't decade-chunked (agriculture, biome)."""
    files = dataset["files"]
    if len(files) != 1:
        raise ValueError(f"Expected exactly one file in dataset {dataset['id']}, found {len(files)}")
    return files[0]
