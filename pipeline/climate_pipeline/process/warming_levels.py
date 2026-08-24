"""Global-warming-level to center-year lookup for this project's model/scenario pairing
(GFDL-ESM4, ssp370).

Source: IPCC AR6 WGI Atlas warming-levels table
(https://github.com/IPCC-WG1/Atlas/blob/main/warming-levels/CMIP6_Atlas_WarmingLevels.csv),
row GFDL-ESM4_r1i1p1f1, columns {1.5,2,3,4}_ssp370 — read live from that published reference, not
recalled from training data, same discipline as ADR-006's live pDSSAT/GFDL-ESM4 coverage check.
Each value is the central year of the 20-year window the Atlas identifies for that warming level
(a 20-year centered rolling mean of global mean surface temperature crossing the threshold,
relative to the 1850-1900 preindustrial baseline).

4.0C is NA in that table for this model/scenario pairing (not reached by 2100) and is excluded
here entirely, not silently substituted with a nearby value.
"""

WARMING_LEVEL_CENTER_YEARS: dict[float, int] = {
    1.5: 2041,
    2.0: 2057,
    3.0: 2083,
}

WINDOW_HALF_WIDTH_YEARS = 10


def window_for_gwl(gwl_c: float) -> tuple[int, int] | None:
    """The (start_year, end_year) 20-year window centered on this GWL's crossing year, or None
    if this warming level isn't reached by GFDL-ESM4/ssp370 within the century."""
    center_year = WARMING_LEVEL_CENTER_YEARS.get(gwl_c)
    if center_year is None:
        return None
    return center_year - WINDOW_HALF_WIDTH_YEARS, center_year + WINDOW_HALF_WIDTH_YEARS
