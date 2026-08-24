import numpy as np
import pandas as pd
import xarray as xr

from climate_pipeline.process.warming_levels import (
    VALID_CENTER_YEARS,
    gwl_for_year,
    preindustrial_reference,
    window_for_year,
)


def _annual_dataset(year_values: dict) -> xr.Dataset:
    # Single lat/lon point so area weighting is a no-op (weight=1 everywhere) — isolates the
    # time-windowing logic these functions actually own; weighting itself is covered in
    # test_process_extract.py's global_area_weighted_mean tests.
    years = sorted(year_values)
    times = pd.to_datetime([f"{y}-07-01" for y in years])
    data = np.array([[[year_values[y]]] for y in years])
    return xr.Dataset(
        {"tas": (["time", "lat", "lon"], data)},
        coords={"time": times, "lat": [0.0], "lon": [0.0]},
    )


def test_window_for_year_uses_the_confirmed_convention():
    # [Y-10, Y+9] -- 10 years before, 9 after, plus Y itself: 20 years total.
    assert window_for_year(2050) == (2040, 2059)


def test_valid_center_years_bounded_by_the_real_fetched_future_span():
    # Future data covers 2015-2100 (see fetch/climate.py); a [Y-10, Y+9] window needs
    # Y-10 >= 2015 and Y+9 <= 2100.
    assert min(VALID_CENTER_YEARS) == 2025
    assert max(VALID_CENTER_YEARS) == 2091


def test_preindustrial_reference_averages_only_1850_to_1900():
    ds = _annual_dataset({1849: 100.0, 1850: 10.0, 1900: 20.0, 1901: 200.0})
    assert preindustrial_reference(ds) == 15.0  # mean of 10 and 20, excludes 1849/1901


def test_gwl_for_year_is_window_mean_minus_preindustrial_reference():
    # Window for 2050 is [2040, 2059]; values outside it confirm windowing actually excludes
    # them, and a known preindustrial_ref checks the subtraction directly.
    ds = _annual_dataset({2039: 999.0, 2050: 12.0, 2059: 8.0, 2060: 999.0})
    gwl = gwl_for_year(ds, 2050, preindustrial_ref=5.0)
    # window mean = mean(12.0, 8.0) = 10.0; GWL = 10.0 - 5.0 = 5.0
    assert gwl == 5.0
