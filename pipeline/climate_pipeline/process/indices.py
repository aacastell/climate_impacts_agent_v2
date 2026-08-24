"""Derived climate indices: consecutive dry days (ETCCDI CDD) and extreme heat days.

Both are computed per calendar year first — a real per-day-then-per-year reduction, not a simple
time-mean — producing a year-indexed grid. Windowing that down to a [Y-10, Y+9] span and
averaging across the window happens the same way as the climate variables (see run.py); this
module only produces the per-year grids.

Unit handling matters here in a way it doesn't for the rest of this pipeline. tas/pr changes
elsewhere are computed as differences (future - baseline), which cancel out any fixed unit
offset/scale — correct whether the underlying values are Kelvin or Celsius. These two indices
instead compare *absolute* values against a fixed threshold (35C, 1mm/day), which is NOT
unit-invariant: comparing a Kelvin value against a Celsius threshold, or a kg/m2/s flux against a
mm/day threshold, would silently produce nonsense. CMIP6/ISIMIP's standard convention is tas in
Kelvin and pr in kg m-2 s-1 — a well-established, near-universal convention across this whole data
ecosystem, not a guess — but this module still reads each dataset's own declared `units`
attribute and converts explicitly rather than assuming blindly, same discipline
extract.py's yield_season_start_year already uses, and fails loudly if units don't match what's
expected instead of silently miscomputing.
"""

import numpy as np
import xarray as xr

# ETCCDI CDD standard: a day counts as "dry" if precip < 1mm. Verified live against the real
# ETCCDI index definition — still widely used post-sunset (the ETCCDI program itself ended in
# 2018) throughout IPCC's own extremes literature.
DRY_DAY_THRESHOLD_MM = 1.0

# A single global threshold, not crop-specific — a deliberate, documented tradeoff. Empirical,
# crop-specific thresholds (maize ~34.8C, soybean ~33.7C, per a 2026 Nature Food study) are more
# scientifically defensible, but would need a credible sourced number per crop (not all findable)
# and would quadruple storage (one grid per crop instead of one shared grid). 35C is the more
# standard of the two commonly-cited round-number thresholds (35C/40C) in the general heat-stress
# literature.
EXTREME_HEAT_THRESHOLD_C = 35.0

_KELVIN_TO_CELSIUS_OFFSET = 273.15
_SECONDS_PER_DAY = 86400


def _tas_in_celsius(data: xr.DataArray) -> xr.DataArray:
    units = data.attrs.get("units", "").strip().upper()
    if units == "K":
        return data - _KELVIN_TO_CELSIUS_OFFSET
    if units in ("DEGC", "DEGREE_C", "C", "CELSIUS"):
        return data
    raise ValueError(f"Unexpected tas units {data.attrs.get('units')!r} — expected K or degC")


def _pr_in_mm_per_day(data: xr.DataArray) -> xr.DataArray:
    units = data.attrs.get("units", "").strip().lower()
    if units in ("kg m-2 s-1", "kg/m2/s", "kg m**-2 s**-1"):
        return data * _SECONDS_PER_DAY
    if units in ("mm/day", "mm day-1", "mm"):
        return data
    raise ValueError(f"Unexpected pr units {data.attrs.get('units')!r} — expected kg m-2 s-1 or mm/day")


def extreme_heat_days_per_year(dataset: xr.Dataset, variable: str = "tas") -> xr.DataArray:
    """Per cell, per calendar year: count of days with tas > EXTREME_HEAT_THRESHOLD_C."""
    celsius = _tas_in_celsius(dataset[variable])
    is_hot = celsius > EXTREME_HEAT_THRESHOLD_C
    return is_hot.groupby("time.year").sum(dim="time")


def consecutive_dry_days_per_year(dataset: xr.Dataset, variable: str = "pr") -> xr.DataArray:
    """Per cell, per calendar year: the longest run of consecutive days with precip below
    DRY_DAY_THRESHOLD_MM (ETCCDI CDD)."""
    mm_per_day = _pr_in_mm_per_day(dataset[variable])
    is_dry = mm_per_day < DRY_DAY_THRESHOLD_MM

    def _longest_run_per_year(year_slice: xr.DataArray) -> xr.DataArray:
        # Longest run of True along the time axis, per cell, for one calendar year's worth of
        # daily booleans. Vectorized over the spatial dims via numpy, not a per-cell Python loop.
        arr = year_slice.values  # (time, lat, lon) bool
        run_lengths = np.zeros(arr.shape[1:], dtype="int32")
        current = np.zeros(arr.shape[1:], dtype="int32")
        for day in arr:
            current = np.where(day, current + 1, 0)
            run_lengths = np.maximum(run_lengths, current)
        return xr.DataArray(run_lengths, dims=year_slice.dims[1:], coords={
            d: year_slice.coords[d] for d in year_slice.dims[1:]
        })

    return is_dry.groupby("time.year").map(_longest_run_per_year)
