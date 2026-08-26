"""Phase 1 of docs/roadmap.md: the deterministic query-time regional lookup. Reads directly from
process_global's precomputed store (processed/global/{output_field}/y{year}.nc) — no LLM, no
recompute, ADR-005 Step 3's "everything downstream is deterministic Python."

Region resolution here is nearest-grid-cell, not bbox-then-geometry: the only real region data
that exists right now (frontend/src/api/questionParsing.ts's KNOWN_REGIONS) is 5 point centroids,
not bounding boxes or polygons. ADR-005 describes bbox-then-geometry for a future, larger region
vocabulary; inventing administrative boundaries for the 5 demo regions to match that design early
isn't an engineering call to make silently, so this reuses the nearest-cell approach the original
5-point MVP already built and tested (process/extract.py's nearest_point_mean/
nearest_point_yield_mean) rather than the windowed-time versions, which don't apply here — each
precomputed field-window file is already a single reduced (lat, lon) grid with no time dimension
at all (see process/run.py's _write_field_window), so no windowing/time logic is needed at
query time, only a plain nearest-cell read.
"""

import math
from pathlib import Path

import xarray as xr

from climate_pipeline.process.run import FIELD_VARIANTS, output_field_name


def field_window_key(base_field: str, kind: str, year: int) -> str:
    """The S3 key process_global wrote this (field, kind, year) to — same naming run.py itself
    uses, not a duplicated convention."""
    return f"processed/global/{output_field_name(base_field, kind)}/y{year}.nc"


def download_field_window(s3, bucket: str, base_field: str, kind: str, year: int, work_dir: Path) -> Path:
    """Downloads the one small (~1MB) object this lookup needs, reusing a local copy if this
    process already fetched it — same whole-object-read pattern ADR-006's storage-format decision
    was built around, not a partial/range read.

    The local cache filename includes the output field, not just Path(key).name: the S3 key's
    leaf is always "y{year}.nc" for every field (the field only appears in the key's directory
    component), so two different fields at the same year would otherwise silently overwrite each
    other's local copy.
    """
    key = field_window_key(base_field, kind, year)
    dest = work_dir / f"{output_field_name(base_field, kind)}_y{year}.nc"
    if not dest.exists():
        work_dir.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, key, str(dest))
    return dest


def nearest_cell_value(path: Path, base_field: str, kind: str, lon: float, lat: float) -> float:
    """The precomputed value at the grid cell nearest (lon, lat) — a plain nearest-neighbor read,
    since the file is already a single reduced (lat, lon) grid, not a time series."""
    output_field = output_field_name(base_field, kind)
    with xr.open_dataset(path) as ds:
        return float(ds[output_field].sel(lon=lon, lat=lat, method="nearest").item())


def lookup_value(s3, bucket: str, base_field: str, kind: str, year: int, lon: float, lat: float, work_dir: Path) -> float:
    """The end-to-end Phase 1 primitive: (field, kind, year, region point) -> precomputed change
    value. `kind` must be one of FIELD_VARIANTS[base_field] — most fields only have "absolute"."""
    if kind not in FIELD_VARIANTS[base_field]:
        raise ValueError(f"{base_field!r} has no {kind!r} variant — valid kinds: {FIELD_VARIANTS[base_field]}")
    path = download_field_window(s3, bucket, base_field, kind, year, work_dir)
    return nearest_cell_value(path, base_field, kind, lon, lat)


def grid_patch(path: Path, base_field: str, kind: str, lon: float, lat: float, radius_deg: float = 2.0) -> dict:
    """A small neighborhood of real precomputed cells around (lon, lat) — real regional shading,
    not decoration. The file this reads from is already the *entire* global grid
    (download_field_window fetches the whole small object, see process/run.py's
    _write_field_window), so this is a local read against data already on disk, not a second S3
    call — the same file nearest_cell_value already reads, just more of it.

    Returns {"lons": [...], "lats": [...], "values": [[...], ...]}, values[i][j] at
    (lats[i], lons[j]). A cell with no real data (ocean, or land the source dataset itself masks
    out) becomes None, not a fabricated 0 or an interpolated guess — the frontend's job is to skip
    rendering those cells, not paper over a real gap in the data.

    Deliberately unrounded, matching nearest_cell_value/lookup_value's own convention — rounding
    is a presentation-layer decision (see api/interpret_handler.py's own round(..., 4) calls),
    made *after* any unit conversion a caller applies (e.g. pr's kg/m^2/s1 -> mm/day), not before.
    Rounding here first would round the raw flux, then a caller's unit conversion would multiply
    an already-rounded number — a real, silent precision bug, not a style preference.
    """
    output_field = output_field_name(base_field, kind)
    with xr.open_dataset(path) as ds:
        da = ds[output_field]
        # A box selection, not a fixed cell count: real ISIMIP resolution (0.5°) means this
        # returns a different cell count near the poles' cos(lat) grid distortion than at the
        # equator, which is correct — it's a real spatial box, not a hardcoded NxN window.
        box = (abs(da["lon"] - lon) <= radius_deg) & (abs(da["lat"] - lat) <= radius_deg)
        patch = da.where(box, drop=True)
        lons = [float(x) for x in patch["lon"].values]
        lats = [float(x) for x in patch["lat"].values]
        values = [
            [None if math.isnan(v) else float(v) for v in row]
            for row in patch.values
        ]
    return {"lons": lons, "lats": lats, "values": values}


def lookup_grid(s3, bucket: str, base_field: str, kind: str, year: int, lon: float, lat: float, work_dir: Path, radius_deg: float = 2.0) -> dict:
    """grid_patch's own S3-backed counterpart to lookup_value — same download-and-cache path,
    same (field, kind, year, region point) inputs, a real spatial patch instead of one scalar."""
    if kind not in FIELD_VARIANTS[base_field]:
        raise ValueError(f"{base_field!r} has no {kind!r} variant — valid kinds: {FIELD_VARIANTS[base_field]}")
    path = download_field_window(s3, bucket, base_field, kind, year, work_dir)
    return grid_patch(path, base_field, kind, lon, lat, radius_deg=radius_deg)
