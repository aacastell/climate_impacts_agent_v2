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

The single-scalar path (lookup_value) is the real, deliberate reduction narrate_handler.py uses
for the narration evidence numbers themselves (ADR-004 Step 4). Grid extraction (a spatial
neighborhood, not one cell) used to live here too, moved client-side
(frontend/src/precomputedFetch.ts) when ADR-004's actual decision — the query API never computes
or extracts shading values for map rendering — was restored after a real, later-acknowledged
drift. grid_patch()/lookup_grid() below are a real, distinct reintroduction, not a revert of that
restoration: they exist for the narration verification gate's driver co-variation check
(docs/adr/adr-007-narration-verification-gate.md's Update; see
pipeline/climate_pipeline/process/covariation.py), a real caller that didn't exist when the
original versions were removed as dead code. Nothing about this reopens map rendering going
through the API — the frontend still fetches and parses precomputed files itself.
"""

from pathlib import Path

import xarray as xr

from climate_pipeline.process.field_names import FIELD_VARIANTS, output_field_name

# Same real-world-meaningful box the frontend uses client-side (frontend/src/precomputedFetch.ts's
# GRID_RADIUS_DEG) — not an arbitrary pixel count, and kept identical so a server-side patch and
# the client-side patch for the same query cover the same cells.
GRID_RADIUS_DEG = 2.0


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


def grid_patch(path: Path, base_field: str, kind: str, lon: float, lat: float, radius_deg: float = GRID_RADIUS_DEG) -> xr.DataArray:
    """The box of grid cells within radius_deg of (lon, lat) — the server-side counterpart to
    frontend/src/precomputedFetch.ts's own box-patch fetch. Needed here for the narration
    verification gate's driver co-variation check, which has to compare several fields over the
    same region's cells at once, not render one. Returns a real xr.DataArray (lat, lon dims),
    NaNs intact — see process/covariation.py for the masking/correlation step."""
    output_field = output_field_name(base_field, kind)
    with xr.open_dataset(path) as ds:
        patch = ds[output_field].where(
            (abs(ds["lat"] - lat) <= radius_deg) & (abs(ds["lon"] - lon) <= radius_deg), drop=True
        )
        return patch.load()


def lookup_grid(
    s3, bucket: str, base_field: str, kind: str, year: int, lon: float, lat: float, work_dir: Path, radius_deg: float = GRID_RADIUS_DEG
) -> xr.DataArray:
    """The end-to-end grid-patch counterpart to lookup_value(): (field, kind, year, region point)
    -> the precomputed change grid within radius_deg of that point. Reuses lookup_value's own
    local download cache — download_field_window() is keyed identically for both, so calling both
    for the same (field, kind, year) never downloads the object twice."""
    if kind not in FIELD_VARIANTS[base_field]:
        raise ValueError(f"{base_field!r} has no {kind!r} variant — valid kinds: {FIELD_VARIANTS[base_field]}")
    path = download_field_window(s3, bucket, base_field, kind, year, work_dir)
    return grid_patch(path, base_field, kind, lon, lat, radius_deg)
