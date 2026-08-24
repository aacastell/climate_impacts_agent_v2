from climate_pipeline.fetch.climate import _files_overlapping


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
    files = [_file("..._2015_2020.nc"), _file("..._2021_2030.nc")]
    # Target: 2026-2100 — 2015_2020 ends (2020) before the target starts
    # (2026), so it's excluded entirely; 2021_2030 overlaps (2026-2030).
    selected = _files_overlapping(files, 2026, 2100)
    assert [f["name"] for f in selected] == ["..._2021_2030.nc"]


def test_raises_if_a_filename_has_no_parseable_year_range():
    try:
        _files_overlapping([_file("no-years-here.nc")], 1995, 2014)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
