from pathlib import Path

import pytest

from climate_pipeline.fetch.climate import WINDOWS, _files_overlapping, fetch_climate_variable


def _file(name: str) -> dict:
    return {"name": name}


def test_selects_only_files_overlapping_the_target_range():
    files = [
        _file("gfdl-esm4_..._historical_tas_..._1981_1990.nc"),
        _file("gfdl-esm4_..._historical_tas_..._1991_2000.nc"),
        _file("gfdl-esm4_..._historical_tas_..._2001_2010.nc"),
        _file("gfdl-esm4_..._historical_tas_..._2011_2014.nc"),
    ]
    # Target: 1995-2014 — should pull 1991_2000 (overlaps 1995-2000),
    # 2001_2010, and 2011_2014, but not 1981_1990 (ends before 1995 starts).
    selected = _files_overlapping(files, 1995, 2014)
    assert [f["name"] for f in selected] == [
        "gfdl-esm4_..._historical_tas_..._1991_2000.nc",
        "gfdl-esm4_..._historical_tas_..._2001_2010.nc",
        "gfdl-esm4_..._historical_tas_..._2011_2014.nc",
    ]


def test_excludes_files_entirely_before_or_after_the_target_range():
    files = [_file("..._2011_2014.nc"), _file("..._2015_2020.nc")]
    # Target: 2015-2100 (the real future window) — 2011_2014 ends (2014)
    # before the target starts (2015), so it's excluded entirely;
    # 2015_2020 overlaps.
    selected = _files_overlapping(files, 2015, 2100)
    assert [f["name"] for f in selected] == ["..._2015_2020.nc"]


def test_raises_if_a_filename_has_no_parseable_year_range():
    try:
        _files_overlapping([_file("no-years-here.nc")], 1995, 2014)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_future_window_starts_at_2015_not_2026():
    # Widened so a 20-year window can be centered on years back to ~2025 —
    # centering on Y needs data back to Y-10. See climate.py's module
    # docstring for the full reasoning.
    assert WINDOWS["future"]["start_year"] == 2015
    assert WINDOWS["future"]["end_year"] == 2100


def test_preindustrial_window_matches_the_ipcc_reference_period():
    # 1850-1900, not ISIMIP's own separate "preindustrial scenario"
    # (1601-1849) — verified live against the real historical dataset's
    # earliest file (1850_1850.nc). See climate.py's module docstring.
    assert WINDOWS["preindustrial"] == {
        "climate_scenario": "historical",
        "start_year": 1850,
        "end_year": 1900,
    }


def test_preindustrial_window_rejects_non_tas_variables():
    # GWL is a temperature-only definition — pr has no preindustrial
    # reference to compute. This should fail before any network call, not
    # silently fetch data nothing will ever use.
    with pytest.raises(ValueError, match="tas-only"):
        fetch_climate_variable("pr", "preindustrial", "some-bucket", Path("/tmp"))
