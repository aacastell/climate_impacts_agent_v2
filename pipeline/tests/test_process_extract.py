import numpy as np
import pandas as pd
import pytest
import xarray as xr

from climate_pipeline.process.extract import (
    absolute_change,
    annual_mean_grid,
    area_weights,
    global_area_weighted_mean,
    grid_mean,
    nearest_point_mean,
    nearest_point_yield_mean,
    percent_change,
    percent_change_grid,
    yield_grid_mean,
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


def test_area_weights_are_larger_near_the_equator_than_poles():
    lat = xr.DataArray([0.0, 60.0, -60.0], dims="lat", coords={"lat": [0.0, 60.0, -60.0]})
    weights = area_weights(lat)
    assert weights.sel(lat=0.0).item() > weights.sel(lat=60.0).item()
    assert weights.mean().item() == pytest.approx(1.0)


def test_global_area_weighted_mean_weights_by_cos_latitude():
    # lat=0 (weight cos(0)=1) has tas=10; lat=60 (weight cos(60)=0.5) has tas=20.
    # Weighted mean = (10*1 + 20*0.5) / (1+0.5) = 13.33...
    times = pd.date_range("2000-01-01", periods=1, freq="YS")
    data = np.array([[[10.0], [20.0]]])  # shape (time=1, lat=2, lon=1)
    ds = xr.Dataset(
        {"tas": (["time", "lat", "lon"], data)},
        coords={"time": times, "lat": [0.0, 60.0], "lon": [0.0]},
    )
    mean = global_area_weighted_mean(ds, "tas", 2000, 2000)
    assert mean == pytest.approx(40.0 / 3.0)


def test_grid_mean_returns_the_full_spatial_grid_not_a_scalar():
    ds = _climate_dataset()  # 3 lon x 2 lat x 6 years, value = calendar year everywhere
    grid = grid_mean(ds, "tas", 2011, 2013)
    assert grid.dims == ("lat", "lon")
    assert grid.shape == (2, 3)
    assert (grid == 2012.0).all()


def test_annual_mean_grid_returns_one_grid_per_year():
    ds = _climate_dataset()  # 3 lon x 2 lat x 6 years, value = calendar year everywhere
    years = annual_mean_grid(ds, "tas")
    assert set(years.coords["year"].values) == {2010, 2011, 2012, 2013, 2014, 2015}
    assert (years.sel(year=2012) == 2012.0).all()


def test_annual_mean_grid_windowed_matches_grid_mean_for_the_same_window():
    # Real equivalence guard for run.py's tas/pr fix: computing the per-year mean once, then
    # slicing+averaging that, must agree with the original direct grid_mean() over the same
    # window — this is a performance fix, not meant to change the actual numbers.
    ds = _climate_dataset()
    direct = grid_mean(ds, "tas", 2011, 2013)
    via_annual = annual_mean_grid(ds, "tas").sel(year=slice(2011, 2013)).mean(dim="year")
    assert np.allclose(direct.values, via_annual.values)


def test_yield_grid_mean_returns_the_full_spatial_grid():
    ds = _yield_dataset(start_year=1990)
    grid = yield_grid_mean(ds, "yield-mai-noirr", 1992, 1994)
    assert grid.dims == ("lat", "lon")
    assert (grid == 1993.0).all()


def test_percent_change_grid_computes_relative_difference_elementwise():
    future = xr.DataArray([[110.0, 50.0]], dims=["lat", "lon"])
    baseline = xr.DataArray([[100.0, 25.0]], dims=["lat", "lon"])
    result = percent_change_grid(future, baseline)
    assert result.values[0, 0] == pytest.approx(10.0)
    assert result.values[0, 1] == pytest.approx(100.0)


def test_percent_change_grid_returns_nan_for_zero_baseline_cells_not_a_crash():
    future = xr.DataArray([[110.0, 5.0]], dims=["lat", "lon"])
    baseline = xr.DataArray([[100.0, 0.0]], dims=["lat", "lon"])
    result = percent_change_grid(future, baseline)
    assert result.values[0, 0] == pytest.approx(10.0)
    assert np.isnan(result.values[0, 1])
