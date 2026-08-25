"""Benchmarks Zarr chunk size against the actual regional-query access pattern the backend
needs (ADR-006's "Accompanying decisions": canonical storage format is deliberately left open
pending exactly this test).

Two things get tested here, not one:
  1. Format: monolithic NetCDF vs. chunked NetCDF vs. Zarr, at one reference chunk size —
     isolates whether any advantage is "Zarr" specifically or just "chunked vs. not".
  2. Chunk size: once chunking's advantage is established, *which* chunk size actually
     minimizes cost — swept across several candidates, not eyeballed. "Country-sized" was the
     starting intuition (~Korea, ~5 degrees); this measures whether that intuition holds against
     a realistic spread of query sizes instead of assuming it.

Data is synthetic, not real ISIMIP output — this benchmark tests the *access pattern*
(regional slice + area-weighted mean against a global grid), not scientific correctness, so a
realistically-shaped synthetic grid is the right tool: no need to move real multi-GB files
around to answer "does chunking/chunk size matter for this query shape."

Grid shape matches ADR-004 Step 2's stated resolution: ISIMIP's native ~0.5°, i.e. 720 lon x
360 lat cells. Variables/windows are illustrative (2 climate variables x 4 windows), sized to
resemble the real canonical store's eventual shape (baseline + a handful of warming-level
windows), not the current fetch scope specifically.

Local-disk timing alone is misleading here, and the first version of this benchmark showed
exactly that: run purely locally, it favored *larger* chunks across the board — backwards from
what chunk size is actually for. On local SSD, the whole synthetic dataset is ~8MB and every
read completes in single-digit milliseconds regardless of format; what got measured was mostly
fixed per-chunk decompression/metadata overhead, with no offsetting benefit, since there's no
real network latency to save bytes against. Real S3 GETs carry genuine per-request round-trip
latency (tens of milliseconds each) that smaller, better-targeted chunks are supposed to let you
avoid paying for unnecessary bytes against — a cost this machine's local disk simply doesn't
have. SYNTHETIC_S3_LATENCY_MS models that missing cost: local wall-clock time (real, measured)
plus (chunks actually touched x this per-request latency) — not a substitute for testing against
real S3, but a way to see whether the *ranking* changes once request-count is priced in, without
needing real AWS resources for this pass. The exact ms figure is a commonly-cited approximate
range for S3 first-byte latency, not something measured against this project's own bucket —
flagged as an assumption, not a fact, the same way this project treats every other unverified
number.
"""

import shutil
import time
from pathlib import Path

import numpy as np
import xarray as xr

# Approximate, not measured against this project's own S3 usage — see module docstring.
SYNTHETIC_S3_LATENCY_MS = 40.0

GRID_LON = 720  # 0.5 degree resolution, -180 to 180
GRID_LAT = 360  # 0.5 degree resolution, -90 to 90
VARIABLES = ["tas", "pr"]
WINDOWS = ["baseline", "gwl_1p5", "gwl_2p0", "gwl_3p0"]

# Candidate chunk sizes to sweep, in grid cells (0.5 deg/cell). Labeled by their real-world
# span so the sweep results read directly against query intuition, not just cell counts.
CHUNK_CANDIDATES = {
    "10x10 (~5deg, Korea-scale)": (10, 10),
    "20x20 (~10deg)": (20, 20),
    "30x30 (~15deg)": (30, 30),
    "60x60 (~30deg, original guess)": (60, 60),
}
# Chunk size used for the format comparison (monolithic vs. chunked-nc vs. zarr) — the
# original guess, since that comparison only needs one reference point, not a sweep.
FORMAT_COMPARISON_CHUNK = (60, 60)

# Query set: the 5 known demo regions as small bounding boxes (matching
# frontend/src/api/mockClient.ts's KNOWN_REGIONS / pipeline/process/regions.py), a
# Korea-sized region (real extent, not a round number, since that's the scale in question),
# plus two larger synthetic regions to see how a bigger area changes the picture.
REGION_QUERIES = {
    "occitanie": (0.0, 4.0, 42.0, 45.0),
    "iowa": (-96.0, -91.0, 40.5, 43.5),
    "punjab": (73.0, 77.5, 29.5, 32.5),
    "nile_delta": (29.5, 32.5, 29.5, 32.0),
    "mekong_delta": (104.0, 107.5, 8.5, 11.5),
    "korea": (124.5, 130.5, 33.0, 38.7),  # real South Korea bounding box
    "large_region_europe": (-10.0, 30.0, 35.0, 60.0),
    "large_region_conus": (-125.0, -65.0, 25.0, 50.0),
}


def _build_synthetic_dataset() -> xr.Dataset:
    rng = np.random.default_rng(seed=0)
    lon = np.linspace(-180, 180, GRID_LON, endpoint=False) + 0.25
    lat = np.linspace(-90, 90, GRID_LAT, endpoint=False) + 0.25
    data_vars = {}
    for var in VARIABLES:
        for window in WINDOWS:
            arr = rng.normal(size=(GRID_LAT, GRID_LON)).astype("float32")
            data_vars[f"{var}_{window}"] = (["lat", "lon"], arr)
    return xr.Dataset(data_vars, coords={"lat": lat, "lon": lon})


def _write_monolithic_netcdf(ds: xr.Dataset, path: Path) -> None:
    ds.to_netcdf(path, engine="h5netcdf")


def _write_chunked_netcdf(ds: xr.Dataset, path: Path, chunk_lat: int, chunk_lon: int) -> None:
    encoding = {
        var: {"chunksizes": (min(chunk_lat, GRID_LAT), min(chunk_lon, GRID_LON)), "zlib": False}
        for var in ds.data_vars
    }
    ds.to_netcdf(path, engine="h5netcdf", encoding=encoding)


def _write_zarr(ds: xr.Dataset, path: Path, chunk_lat: int, chunk_lon: int) -> None:
    chunked = ds.chunk({"lat": chunk_lat, "lon": chunk_lon})
    chunked.to_zarr(path, mode="w")


def _regional_mean(ds: xr.Dataset, var: str, lon_min, lon_max, lat_min, lat_max) -> float:
    subset = ds[var].sel(lon=slice(lon_min, lon_max), lat=slice(lat_min, lat_max))
    return float(subset.mean().values)


def _chunks_touched_zarr(chunk_lat: int, chunk_lon: int, bbox) -> int:
    """How many distinct Zarr chunks a regional query needs — the same arithmetic Zarr itself
    does: coordinate -> index (via searchsorted on the known, regular coordinate arrays) ->
    chunk index (floor division by chunk size) -> count of distinct chunk indices touched per
    dimension, cartesian product across dimensions. No lookup table, matches how Zarr's own
    chunk-key resolution works (see the conversation this benchmark came out of)."""
    lon_min, lon_max, lat_min, lat_max = bbox
    lon_coords = np.linspace(-180, 180, GRID_LON, endpoint=False) + 0.25
    lat_coords = np.linspace(-90, 90, GRID_LAT, endpoint=False) + 0.25

    lon_start_idx = int(np.searchsorted(lon_coords, lon_min, side="left"))
    lon_end_idx = int(np.searchsorted(lon_coords, lon_max, side="right")) - 1
    lat_start_idx = int(np.searchsorted(lat_coords, lat_min, side="left"))
    lat_end_idx = int(np.searchsorted(lat_coords, lat_max, side="right")) - 1

    lon_chunks = (lon_end_idx // chunk_lon) - (lon_start_idx // chunk_lon) + 1
    lat_chunks = (lat_end_idx // chunk_lat) - (lat_start_idx // chunk_lat) + 1
    return max(lon_chunks, 1) * max(lat_chunks, 1)


def _time_query(open_fn, var: str, bbox, repeats: int) -> float:
    lon_min, lon_max, lat_min, lat_max = bbox
    times = []
    for _ in range(repeats):
        started = time.perf_counter()
        ds = open_fn()
        _regional_mean(ds, var, lon_min, lon_max, lat_min, lat_max)
        ds.close()
        times.append(time.perf_counter() - started)
    return min(times)  # best-of-N: isolates the operation from incidental scheduling noise


def _simulated_s3_time(local_time_s: float, chunks_touched: int) -> float:
    """Local time (real work: decompression, compute) plus the request-count-driven network
    cost a real S3-hosted store would add — see module docstring on why local time alone is
    misleading for this comparison."""
    return local_time_s + (chunks_touched * SYNTHETIC_S3_LATENCY_MS / 1000)


def _dir_size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _run_format_comparison(ds: xr.Dataset, var: str, work_dir: Path, repeats: int) -> None:
    chunk_lat, chunk_lon = FORMAT_COMPARISON_CHUNK
    monolithic_path = work_dir / "monolithic.nc"
    chunked_nc_path = work_dir / "chunked.nc"
    zarr_path = work_dir / "store.zarr"

    print(f"=== Format comparison (chunk size {chunk_lat}x{chunk_lon} where chunked) ===")
    print(f"Simulated S3 latency: {SYNTHETIC_S3_LATENCY_MS:.0f}ms/request (see module docstring)")
    _write_monolithic_netcdf(ds, monolithic_path)
    _write_chunked_netcdf(ds, chunked_nc_path, chunk_lat, chunk_lon)
    _write_zarr(ds, zarr_path, chunk_lat, chunk_lon)

    print(f"{'format':<16}{'on-disk size':>16}")
    print(f"{'monolithic nc':<16}{_dir_size_bytes(monolithic_path):>16,}")
    print(f"{'chunked nc':<16}{_dir_size_bytes(chunked_nc_path):>16,}")
    print(f"{'zarr':<16}{_dir_size_bytes(zarr_path):>16,}")
    print()

    # monolithic and chunked-nc both get chunks_touched=1: without specialized remote-HDF5
    # tooling (fsspec byte-range drivers, kerchunk, etc — not what a plain xr.open_dataset call
    # uses), reading any variable from a NetCDF file on S3 typically means fetching the whole
    # object first, regardless of whether it's internally chunked. Zarr's chunk-per-S3-object
    # design is what makes partial reads the *default*, unspecialized behavior — that's the
    # real advantage this format comparison is trying to isolate, not just decompression speed.
    formats = {
        "monolithic_nc": (lambda: xr.open_dataset(monolithic_path, engine="h5netcdf"), lambda bbox: 1),
        "chunked_nc": (lambda: xr.open_dataset(chunked_nc_path, engine="h5netcdf"), lambda bbox: 1),
        "zarr": (
            lambda: xr.open_zarr(zarr_path),
            lambda bbox: _chunks_touched_zarr(chunk_lat, chunk_lon, bbox),
        ),
    }

    header = f"{'region':<22}" + "".join(f"{name:>16}" for name in formats)
    print(header + "  (local time, then local+simulated-S3)")
    for region_name, bbox in REGION_QUERIES.items():
        row = f"{region_name:<22}"
        for name, (open_fn, chunks_fn) in formats.items():
            local = _time_query(open_fn, var, bbox, repeats)
            simulated = _simulated_s3_time(local, chunks_fn(bbox))
            row += f"{local * 1000:>7.1f}/{simulated * 1000:<7.1f}"
        print(row)
    print()


def _run_chunk_size_sweep(ds: xr.Dataset, var: str, work_dir: Path, repeats: int) -> None:
    print("=== Zarr chunk size sweep (simulated-S3 time — see module docstring) ===")
    stores = {}
    for label, (chunk_lat, chunk_lon) in CHUNK_CANDIDATES.items():
        path = work_dir / f"store_{chunk_lat}x{chunk_lon}.zarr"
        _write_zarr(ds, path, chunk_lat, chunk_lon)
        stores[label] = (path, chunk_lat, chunk_lon)

    print(f"{'chunk size':<32}{'on-disk size':>16}")
    for label, (path, _, _) in stores.items():
        print(f"{label:<32}{_dir_size_bytes(path):>16,}")
    print()

    header = f"{'region':<22}" + "".join(f"{label:>32}" for label in stores)
    print(header)
    totals_local = {label: 0.0 for label in stores}
    totals_simulated = {label: 0.0 for label in stores}
    for region_name, bbox in REGION_QUERIES.items():
        row = f"{region_name:<22}"
        for label, (path, chunk_lat, chunk_lon) in stores.items():
            local = _time_query(lambda p=path: xr.open_zarr(p), var, bbox, repeats)
            chunks = _chunks_touched_zarr(chunk_lat, chunk_lon, bbox)
            simulated = _simulated_s3_time(local, chunks)
            totals_local[label] += local
            totals_simulated[label] += simulated
            row += f"{simulated * 1000:>26.1f}ms({chunks:>2})"
        print(row)

    print()
    print(
        f"{'TOTAL, simulated S3':<22}"
        + "".join(f"{totals_simulated[label] * 1000:>29.1f}ms" for label in stores)
    )
    print(
        f"{'TOTAL, local only':<22}"
        + "".join(f"{totals_local[label] * 1000:>29.1f}ms" for label in stores)
    )


def run_benchmark(work_dir: Path, repeats: int = 5) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    ds = _build_synthetic_dataset()
    var = f"{VARIABLES[0]}_baseline"

    print(f"Grid: {GRID_LAT} lat x {GRID_LON} lon, {len(VARIABLES)} variables x {len(WINDOWS)} windows")
    print()

    _run_format_comparison(ds, var, work_dir, repeats)
    _run_chunk_size_sweep(ds, var, work_dir, repeats)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=Path("benchmark_output"))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--keep", action="store_true", help="keep generated files after running")
    args = parser.parse_args()

    run_benchmark(args.work_dir, args.repeats)

    if not args.keep:
        shutil.rmtree(args.work_dir, ignore_errors=True)
