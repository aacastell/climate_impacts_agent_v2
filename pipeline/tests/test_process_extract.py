import numpy as np
import pandas as pd
import pytest
import xarray as xr

from climate_pipeline.process.extract import (
    absolute_change,
    nearest_point_mean,
    nearest_point_yield_mean,
    percent_change,
    yield_season_start_year,
)


def _climate_dataset() -> xr.Dataset:
    # 3 lon x 2 lat x 6 years (2010-2015), "tas" = year index so the mean over
    # a known sub-range is easy to check by hand.
    lons = [0.0, 10.0, 20.0]
    lats = [40.0, 50.0]
    times = pd.date_range("2010-01-01", periods=6, freq="YS")
    data = np.zeros((6, 2, 3))
    for i, t in enumerate(times):
        data[i, :, :] = t.year
    return xr.Dataset(
        {"tas": (["time", "lat", "lon"], data)},
        coords={"time": times, "lat": lats, "lon": lons},
    )


def test_nearest_point_mean_selects_nearest_cell_and_windows_by_year():
    ds = _climate_dataset()
    # Nearest to (9.0, 49.0) is (lon=10.0, lat=50.0); values there equal the
    # calendar year for every timestep, so the mean over 2011-2013 is 2012.
    mean = nearest_point_mean(ds, "tas", lon=9.0, lat=49.0, start_year=2011, end_year=2013)
    assert mean == 2012.0


def _yield_dataset(start_year: int = 1990) -> xr.Dataset:
    lons = [0.0, 10.0]
    lats = [40.0]
    # Unitless integer season index, not a real time axis — see extract.py's
    # module docstring on why LPJmL yield output is shaped this way.
    season_index = np.arange(10)
    data = np.zeros((10, 1, 2))
    for i in season_index:
        data[i, :, :] = start_year + i
    ds = xr.Dataset(
        {"yield-mai-noirr": (["time", "lat", "lon"], data)},
        coords={"time": season_index, "lat": lats, "lon": lons},
    )
    ds["time"].attrs["units"] = f"growing seasons since {start_year}-01-01"
    return ds


def test_yield_season_start_year_parses_the_units_attribute():
    ds = _yield_dataset(start_year=1990)
    assert yield_season_start_year(ds) == 1990


def test_yield_season_start_year_raises_on_unparseable_units():
    ds = _yield_dataset()
    ds["time"].attrs["units"] = "not a recognized format"
    with pytest.raises(ValueError):
        yield_season_start_year(ds)


def test_nearest_point_yield_mean_converts_season_index_to_calendar_years():
    ds = _yield_dataset(start_year=1990)
    # Values equal the calendar year at every season, so the mean over
    # 1992-1994 (season indices 2-4) is 1993.
    mean = nearest_point_yield_mean(ds, "yield-mai-noirr", lon=1.0, lat=40.0, start_year=1992, end_year=1994)
    assert mean == 1993.0


def test_absolute_change_is_a_plain_difference():
    assert absolute_change(future_mean=15.0, baseline_mean=13.0) == 2.0


def test_percent_change_computes_relative_difference():
    assert percent_change(future_mean=110.0, baseline_mean=100.0) == 10.0


def test_percent_change_raises_on_zero_baseline():
    with pytest.raises(ValueError):
        percent_change(future_mean=5.0, baseline_mean=0.0)
