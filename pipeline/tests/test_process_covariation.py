import numpy as np
import pytest
import xarray as xr

from climate_pipeline.process.covariation import (
    MIN_CELLS_FOR_CONFIDENCE,
    driver_covariation,
    spearman_correlation,
)


def _grid(values) -> xr.DataArray:
    arr = np.array(values, dtype=float)
    return xr.DataArray(arr, dims=["lat", "lon"], coords={"lat": range(arr.shape[0]), "lon": range(arr.shape[1])})


def test_spearman_correlation_is_plus_one_for_a_perfectly_monotonic_pair():
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    assert spearman_correlation(a, b) == pytest.approx(1.0)


def test_spearman_correlation_is_minus_one_for_an_inverted_pair():
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = np.array([50.0, 40.0, 30.0, 20.0, 10.0])
    assert spearman_correlation(a, b) == pytest.approx(-1.0)


def test_spearman_correlation_is_robust_to_nonlinear_but_monotonic_relationships():
    # Spearman is rank-based — a nonlinear (here, quadratic-in-magnitude) but still monotonic
    # relationship should still score close to 1, unlike Pearson, which would be pulled down by
    # the nonlinearity. This is the real reason Spearman was chosen over Pearson (module docstring).
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = a**3
    assert spearman_correlation(a, b) == pytest.approx(1.0)


def test_spearman_correlation_returns_zero_for_a_constant_array_not_nan():
    a = np.array([1.0, 2.0, 3.0])
    b = np.array([5.0, 5.0, 5.0])
    assert spearman_correlation(a, b) == 0.0


def test_spearman_correlation_average_ranks_a_genuine_tie():
    # Regression: a naive rank-via-argsort (no tie correction) assigns a tied value's arbitrary
    # sort position as its rank instead of the shared average rank — b's two "20"s would get
    # different ranks purely from their original array position, not their actual (equal) value.
    # Correct average ranks: a -> [0,1,2,3], b -> [0, 1.5, 1.5, 3] -> hand-computed rho below.
    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([10.0, 20.0, 20.0, 30.0])
    r = spearman_correlation(a, b)
    assert r == pytest.approx(0.9486832980505138, rel=1e-9)
    assert r != pytest.approx(1.0)  # the tie's real effect, not silently ignored


def test_spearman_correlation_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        spearman_correlation(np.array([1.0, 2.0]), np.array([1.0]))


def test_spearman_correlation_rejects_fewer_than_two_cells():
    with pytest.raises(ValueError, match="at least 2"):
        spearman_correlation(np.array([1.0]), np.array([1.0]))


def test_driver_covariation_ranks_a_strongly_correlated_driver_above_a_weak_one():
    # yield decline tracks extreme_heat_days closely (monotonic) but is essentially unrelated to
    # consecutive_dry_days in this synthetic patch.
    yield_grid = _grid([[10.0, 8.0, 6.0], [4.0, 2.0, 0.0]])
    driver_grids = {
        "extreme_heat_days": _grid([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),  # inversely tracks yield -> strong |r|
        "consecutive_dry_days": _grid([[3.0, 1.0, 4.0], [1.0, 5.0, 2.0]]),  # unrelated -> weak |r|
    }

    result = driver_covariation(driver_grids, yield_grid)

    assert result["extreme_heat_days"]["r"] == pytest.approx(-1.0)
    assert abs(result["extreme_heat_days"]["r"]) > abs(result["consecutive_dry_days"]["r"])
    assert result["extreme_heat_days"]["cell_count"] == 6


def test_driver_covariation_masks_cells_where_yield_is_nan():
    # LPJmL's own output is null outside cells where the crop is actually grown (module
    # docstring) — those cells must not enter the correlation at all, not be treated as zero.
    yield_grid = _grid([[10.0, np.nan, 6.0], [np.nan, 2.0, 0.0]])
    driver_grids = {"tas": _grid([[1.0, 99.0, 3.0], [99.0, 5.0, 6.0]])}

    result = driver_covariation(driver_grids, yield_grid)

    assert result["tas"]["cell_count"] == 4  # only the 4 cells where yield is real


def test_driver_covariation_flags_low_confidence_below_the_cell_floor():
    small_yield = _grid([[10.0, 8.0], [6.0, 4.0]])  # 4 real cells, well under MIN_CELLS_FOR_CONFIDENCE
    driver_grids = {"tas": _grid([[1.0, 2.0], [3.0, 4.0]])}

    result = driver_covariation(driver_grids, small_yield)

    assert result["tas"]["cell_count"] == 4
    assert result["tas"]["cell_count"] < MIN_CELLS_FOR_CONFIDENCE
    assert result["tas"]["low_confidence"] is True


def test_driver_covariation_returns_none_r_when_fewer_than_two_valid_cells():
    yield_grid = _grid([[10.0, np.nan], [np.nan, np.nan]])
    driver_grids = {"tas": _grid([[1.0, 2.0], [3.0, 4.0]])}

    result = driver_covariation(driver_grids, yield_grid)

    assert result["tas"]["r"] is None
    assert result["tas"]["cell_count"] == 1
    assert result["tas"]["low_confidence"] is True


def test_driver_covariation_rejects_a_shape_mismatch():
    yield_grid = _grid([[10.0, 8.0], [6.0, 4.0]])
    mismatched = xr.DataArray(np.array([1.0, 2.0, 3.0]), dims=["lat"], coords={"lat": [0, 1, 2]})

    with pytest.raises(ValueError, match="does not match"):
        driver_covariation({"tas": mismatched}, yield_grid)
