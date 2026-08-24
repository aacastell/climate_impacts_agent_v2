import numpy as np
import pandas as pd
import pytest
import xarray as xr

from climate_pipeline.process.indices import (
    consecutive_dry_days_per_year,
    extreme_heat_days_per_year,
)


def _daily_dataset(variable: str, units: str, year_values: dict) -> xr.Dataset:
    # year_values: {year: [daily values for that year]} -- single lat/lon point.
    all_times = []
    all_values = []
    for year, values in year_values.items():
        times = pd.date_range(f"{year}-01-01", periods=len(values), freq="D")
        all_times.extend(times)
        all_values.extend(values)
    data = np.array(all_values).reshape(-1, 1, 1)
    ds = xr.Dataset(
        {variable: (["time", "lat", "lon"], data)},
        coords={"time": all_times, "lat": [0.0], "lon": [0.0]},
    )
    ds[variable].attrs["units"] = units
    return ds


def test_extreme_heat_days_counts_days_above_threshold_kelvin_input():
    # 35C = 308.15K. 3 of these 5 days are above threshold.
    year_2000 = [300.0, 310.0, 309.0, 308.16, 300.0]
    ds = _daily_dataset("tas", "K", {2000: year_2000})
    result = extreme_heat_days_per_year(ds)
    assert result.sel(year=2000).item() == 3


def test_extreme_heat_days_rejects_unexpected_units():
    ds = _daily_dataset("tas", "furlongs", {2000: [300.0]})
    with pytest.raises(ValueError, match="Unexpected tas units"):
        extreme_heat_days_per_year(ds)


def test_consecutive_dry_days_finds_the_longest_run_kg_m2_s1_input():
    # kg m-2 s-1 -> mm/day via *86400; 1mm/day is the ETCCDI dry-day threshold.
    wet = 2.0 / 86400  # 2mm/day, wet
    dry = 0.5 / 86400  # 0.5mm/day, dry
    # 4 dry, 1 wet, 6 dry (the longest run), 2 wet.
    year_2000 = [dry] * 4 + [wet] + [dry] * 6 + [wet] * 2
    ds = _daily_dataset("pr", "kg m-2 s-1", {2000: year_2000})
    result = consecutive_dry_days_per_year(ds)
    assert result.sel(year=2000).item() == 6


def test_consecutive_dry_days_rejects_unexpected_units():
    ds = _daily_dataset("pr", "furlongs", {2000: [0.0]})
    with pytest.raises(ValueError, match="Unexpected pr units"):
        consecutive_dry_days_per_year(ds)
