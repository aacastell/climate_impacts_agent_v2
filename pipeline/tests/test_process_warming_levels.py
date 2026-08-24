from climate_pipeline.process.warming_levels import WARMING_LEVEL_CENTER_YEARS, window_for_gwl


def test_window_for_gwl_centers_on_the_looked_up_year():
    assert window_for_gwl(1.5) == (2031, 2051)
    assert window_for_gwl(2.0) == (2047, 2067)
    assert window_for_gwl(3.0) == (2073, 2093)


def test_window_for_gwl_returns_none_for_unreached_levels():
    assert window_for_gwl(4.0) is None
    assert 4.0 not in WARMING_LEVEL_CENTER_YEARS


def test_every_window_fits_inside_the_fetched_future_span():
    # Fetch only pulls 2026-2100 (see fetch/climate.py) — a window that fell
    # outside that span would silently read incomplete data.
    for gwl_c in WARMING_LEVEL_CENTER_YEARS:
        start_year, end_year = window_for_gwl(gwl_c)
        assert 2026 <= start_year and end_year <= 2100
