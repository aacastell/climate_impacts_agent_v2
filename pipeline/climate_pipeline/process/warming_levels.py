"""Self-computed global warming level (GWL), not looked up from a fixed checkpoint table.

Per year Y in the future projection, a 20-year window [Y-10, Y+9] is drawn around it (confirmed
convention — 10 years before, 9 years after, plus Y itself), the area-weighted global mean `tas`
over that window is computed, and GWL(Y) is that value minus the preindustrial reference. This
falls straight out of the same computation the per-cell change grids already need — there's no
separate lookup step, and no dependency on the IPCC AR6 Atlas's 4 discrete checkpoints (1.5/2/3/4C)
this project used in an earlier pass.

The preindustrial reference is real ISIMIP data, not an externally-sourced number: 1850-1900,
the IPCC standard GWL reference period, is simply the start of ISIMIP's own `historical` GFDL-ESM4
dataset (verified live against the real catalog — the earliest file is
`..._historical_tas_global_daily_1850_1850.nc`), fetched via `fetch_tas_preindustrial`. Reusing
the same dataset/bias-adjustment pipeline as everything else in this project avoids mixing in a
different model's bias-adjustment, which an externally-sourced "preindustrial temperature" number
would risk.
"""

import xarray as xr

from climate_pipeline.process.extract import global_area_weighted_mean

PREINDUSTRIAL_START_YEAR = 1850
PREINDUSTRIAL_END_YEAR = 1900

WINDOW_YEARS_BEFORE = 10
WINDOW_YEARS_AFTER = 9

# The real, data-bounded range of years a 20-year [Y-10, Y+9] window can be computed for, given
# the fetched future span (2015-2100): Y-10 >= 2015 => Y >= 2025; Y+9 <= 2100 => Y <= 2091.
VALID_CENTER_YEARS = range(2025, 2092)


def window_for_year(year: int) -> tuple[int, int]:
    """The [start_year, end_year] 20-year window centered on `year`, per the confirmed
    [Y-10, Y+9] convention."""
    return year - WINDOW_YEARS_BEFORE, year + WINDOW_YEARS_AFTER


def preindustrial_reference(dataset: xr.Dataset, variable: str = "tas") -> float:
    """Area-weighted global mean `tas` over 1850-1900 — the fixed GWL reference point."""
    return global_area_weighted_mean(dataset, variable, PREINDUSTRIAL_START_YEAR, PREINDUSTRIAL_END_YEAR)


def gwl_for_year(dataset: xr.Dataset, year: int, preindustrial_ref: float, variable: str = "tas") -> float:
    """GWL for `year`: area-weighted global mean tas over its [Y-10, Y+9] window, minus the
    preindustrial reference."""
    start_year, end_year = window_for_year(year)
    window_mean = global_area_weighted_mean(dataset, variable, start_year, end_year)
    return window_mean - preindustrial_ref
