"""Pure(-ish) extraction/statistics functions for the process stage.

Two families of functions here: point-based (nearest-grid-cell to one lon/lat — the original
5-fixed-region MVP's extraction method, kept but no longer called by run.py now that regional
extraction is out of scope for this pipeline — see ADR-006 Step 3, regional aggregation stays
query-time) and grid-wide (whole 720x360 field at once — what the real global precompute grid
actually needs).

Climate driver files (tas, pr) use standard CF time/lat/lon dimensions. LPJmL yield output files
do not: per the ISIMIP/GGCMI protocol, crop yield is reported per growing season, not per
calendar date, so these files use a unitless integer season-index coordinate instead of a real
time axis. This module derives the real calendar year for each season index from that
coordinate's own `units` attribute rather than hardcoding a start year, and fails loudly if that
attribute doesn't match the documented convention. Confirmed against a real downloaded file: LPJmL
noirr output uses `units="growing seasons since 1601-01-01 00:00:00"` and `calendar="360_day"` —
not a real CF time axis at all, which is why the caller must open these files with
`decode_times=False` (see run.py's `_open_yield_dataset`) rather than letting xarray try and fail
to CF-decode "growing seasons" as a time unit.
"""

import re
from pathlib import Path

import numpy as np
import xarray as xr

_SEASON_UNITS_RE = re.compile(r"since (\d{4})")


def nearest_point_mean(
    dataset: xr.Dataset, variable: str, lon: float, lat: float, start_year: int, end_year: int
) -> float:
    """Mean of `variable` at the grid cell nearest (lon, lat), over calendar years
    [start_year, end_year], using a real CF time coordinate."""
    point = dataset[variable].sel(lon=lon, lat=lat, method="nearest")
    windowed = point.sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31"))
    return float(windowed.mean())


def yield_season_start_year(dataset: xr.Dataset, time_dim: str = "time") -> int:
    """The calendar year season index 0 corresponds to, parsed from the season coordinate's own
    `units` attribute — see module docstring."""
    units = dataset[time_dim].attrs.get("units", "")
    match = _SEASON_UNITS_RE.search(units)
    if not match:
        raise ValueError(
            f"Could not parse a start year from yield time coordinate units {units!r} — "
            "expected something like 'growing seasons since 1850-01-01'"
        )
    return int(match.group(1))


def nearest_point_yield_mean(
    dataset: xr.Dataset,
    variable: str,
    lon: float,
    lat: float,
    start_year: int,
    end_year: int,
    time_dim: str = "time",
) -> float:
    """Mean of a yield `variable` at the grid cell nearest (lon, lat), over calendar years
    [start_year, end_year] — converts the season-index coordinate to calendar years first."""
    season_start = yield_season_start_year(dataset, time_dim)
    point = dataset[variable].sel(lon=lon, lat=lat, method="nearest")
    season_years = season_start + point[time_dim].values
    in_window = (season_years >= start_year) & (season_years <= end_year)
    windowed = point.isel({time_dim: in_window})
    return float(windowed.mean())


def absolute_change(future_mean: float, baseline_mean: float) -> float:
    """Absolute change from baseline — e.g. temperature, in the same units as the input."""
    return future_mean - baseline_mean


def percent_change_grid(future_grid: xr.DataArray, baseline_grid: xr.DataArray) -> xr.DataArray:
    """Grid-wide percent change from baseline. A zero-baseline cell doesn't raise — a global grid
    legitimately has cells with no meaningful baseline (ocean, non-arable land for yield), and
    one such cell shouldn't crash the whole computation. Those cells become NaN, not a fabricated
    number and not a crash."""
    return xr.where(baseline_grid != 0, (future_grid - baseline_grid) / baseline_grid * 100, np.nan)


def area_weights(lat: xr.DataArray) -> xr.DataArray:
    """cos(latitude), normalized to mean 1 — corrects for a lat/lon grid's cells shrinking in
    real area toward the poles despite equal angular size. Standard technique, needed for any
    true *global* mean (as opposed to a naive unweighted mean across cells, which would
    overweight the poles)."""
    weights = np.cos(np.deg2rad(lat))
    return weights / weights.mean()


def global_area_weighted_mean(dataset: xr.Dataset, variable: str, start_year: int, end_year: int) -> float:
    """Area-weighted global mean of `variable` over calendar years [start_year, end_year] — a
    single scalar, e.g. for the GWL calculation (warming_levels.py)."""
    windowed = dataset[variable].sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31"))
    weights = area_weights(dataset["lat"])
    # float(), not .item(): _open_climate_dataset uses open_mfdataset, so this is dask-backed —
    # xarray's DataArray.item() doesn't delegate through dask (confirmed via a real CodeBuild
    # crash: "'item' is not yet a valid method on dask arrays"), but float() does, computing the
    # array as needed either way.
    return float(windowed.weighted(weights).mean())


def grid_mean(dataset: xr.Dataset, variable: str, start_year: int, end_year: int) -> xr.DataArray:
    """Per-cell mean of `variable` over calendar years [start_year, end_year] — the full spatial
    grid, not a single point or a spatial reduction. This is the actual per-cell change-grid
    input; no area weighting here, since nothing is being spatially reduced."""
    windowed = dataset[variable].sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31"))
    return windowed.mean(dim="time")


def annual_mean_grid(dataset: xr.Dataset, variable: str, time_dim: str = "time") -> xr.DataArray:
    """Per-cell, per-calendar-year mean of `variable`, computed once for the whole dataset — the
    reusable input a 20-year window average should be built from, instead of calling grid_mean()
    fresh per window.

    Real, confirmed-live reason this exists: run.py's tas/pr branches originally called grid_mean()
    once per future window (67 times), each a fresh .sel(time=slice(...)).mean() over the raw
    daily dataset. Since consecutive windows overlap in 19 of their 20 years, that's ~20x
    redundant re-reads of the same daily data — and it TIMED_OUT three real CodeBuild runs
    (process_tas, process_pr, process_extreme_heat_days) at the account's real ~45-minute cap.
    Computing the per-year mean once, then slicing+averaging that much smaller array per window
    (see run.py), cuts total raw-data touches by roughly the same ~20x this was costing.

    Same eager-per-year-materialization shape as indices.py's functions, for the same reason:
    xarray's lazy .groupby(...).mean() on a large dask array is a real, confirmed performance gap
    (extreme_heat_days_per_year timed out with it; the eager version finished the same dataset in
    under 8 minutes), not something to trust again just because it looks simpler.

    One small, accepted approximation, not hidden: this means "mean of annual means," not "mean
    of every raw day" — identical if every year has the same day count, and differs only by a
    scientifically negligible amount otherwise (a leap-year-sized rounding effect, not a
    meaningful one), the same order of approximation this project already accepts elsewhere.
    """
    data = dataset[variable]

    def _mean_per_year(year_slice: xr.DataArray) -> xr.DataArray:
        arr = year_slice.values  # forces this one year to materialize, not the whole dataset at once
        means = arr.mean(axis=0)
        return xr.DataArray(means, dims=year_slice.dims[1:], coords={d: year_slice.coords[d] for d in year_slice.dims[1:]})

    return data.groupby(f"{time_dim}.year").map(_mean_per_year)


def annual_mean_grid_per_file(paths: list[Path], variable: str, time_dim: str = "time") -> xr.DataArray:
    """Same result as annual_mean_grid(), computed a different way: each file opened and reduced
    to its own per-year means independently (xr.open_dataset, no multi-file combine), then the
    small already-reduced results concatenated — instead of xr.open_mfdataset(combine="by_coords")
    building one combined lazy dataset spanning every file before any reduction happens.

    Why this is exactly equivalent, not an approximation: this project's raw fetch always splits
    files on decade boundaries (see fetch/climate.py) — no single calendar year's data is ever
    split across two files. A per-year mean is therefore always computable from exactly one file,
    so computing it per-file and concatenating is mathematically identical to computing it from
    one dataset covering every file, not a second approximation stacked on annual_mean_grid()'s
    own "mean of annual means" one. Verified directly, not assumed: a real numerical-equivalence
    test against annual_mean_grid() on real downloaded pr/tas data (see the CDD/pr timeout
    investigation) confirmed identical output before this was trusted.

    Real, still-not-fully-explained reason this exists, honestly stated rather than overclaimed:
    `pr`'s process_field CodeBuild run timed out (~2600s) even after annual_mean_grid() fixed the
    same timeout for tas and extreme_heat_days — reproducibly, standalone, with byte-identical
    encoding to tas confirmed directly (dtype, chunk shape, compression). The exact mechanism
    inside xarray/dask's multi-file combine was never pinned down at small local scale (2 of 9
    files showed no reproducible slowdown either) — this sidesteps the whole combine step instead
    of requiring that root cause to be found, on the theory that whatever's expensive about
    combining 9 files' coordinate/chunk metadata together can't be expensive if that combine never
    happens at all.
    """
    per_file_results = [annual_mean_grid(xr.open_dataset(path, chunks={}), variable, time_dim) for path in paths]
    return xr.concat(per_file_results, dim="year")


def yield_grid_mean(
    dataset: xr.Dataset, variable: str, start_year: int, end_year: int, time_dim: str = "time"
) -> xr.DataArray:
    """Per-cell mean of a yield `variable` over calendar years [start_year, end_year] — the
    grid-wide counterpart to nearest_point_yield_mean, converting the season-index coordinate to
    calendar years first."""
    season_start = yield_season_start_year(dataset, time_dim)
    season_years = season_start + dataset[time_dim].values
    in_window = (season_years >= start_year) & (season_years <= end_year)
    windowed = dataset[variable].isel({time_dim: in_window})
    return windowed.mean(dim=time_dim)
