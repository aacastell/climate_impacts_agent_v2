"""Pure(-ish) extraction/statistics functions for the process stage.

Nearest-grid-cell extraction, not area-weighted — see pipeline/README.md's MVP note: no region
boundary polygons exist yet for these 5 named regions, only lon/lat points (regions.py), so
there's nothing to area-weight against. Revisit once real region boundaries exist (ADR-006 Step 3
describes the eventual area-weighted design).

Climate driver files (tas, pr) use standard CF time/lat/lon dimensions. LPJmL yield output files
do not: per the ISIMIP/GGCMI protocol, crop yield is reported per growing season, not per
calendar date, so these files use a unitless integer season-index coordinate instead of a real
time axis. This module derives the real calendar year for each season index from that
coordinate's own `units` attribute (e.g. "growing seasons since 1850-01-01") rather than
hardcoding a start year, and fails loudly if that attribute doesn't match the documented
convention — this hasn't yet been verified against a real downloaded file (the fetch build was
still running when this was written), so treat yield_season_start_year's behavior as unconfirmed
until checked against one.
"""

import re

import xarray as xr

_SEASON_UNITS_RE = re.compile(r"since (\d{4})")


def nearest_point_mean(
    dataset: xr.Dataset, variable: str, lon: float, lat: float, start_year: int, end_year: int
) -> float:
    """Mean of `variable` at the grid cell nearest (lon, lat), over calendar years
    [start_year, end_year], using a real CF time coordinate."""
    point = dataset[variable].sel(lon=lon, lat=lat, method="nearest")
    windowed = point.sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31"))
    return float(windowed.mean().item())


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
    return float(windowed.mean().item())


def absolute_change(future_mean: float, baseline_mean: float) -> float:
    """Absolute change from baseline — e.g. temperature, in the same units as the input."""
    return future_mean - baseline_mean


def percent_change(future_mean: float, baseline_mean: float) -> float:
    """Percent change from baseline — e.g. precipitation, yield. A zero baseline has no
    meaningful percent change; callers should treat that as a data problem, not silently divide
    by it."""
    if baseline_mean == 0:
        raise ValueError("Cannot compute percent change from a zero baseline")
    return (future_mean - baseline_mean) / baseline_mean * 100
