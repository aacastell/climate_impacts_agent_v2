"""Deterministic driver/yield co-variation — the near-term half of the mechanistic-attribution
signal named in docs/adr/adr-007-narration-verification-gate.md's Update: a real, computable
proxy for "which climate driver's spatial pattern best explains this region's yield pattern,"
built entirely from grids the process stage already writes (no new data collection). Not causal
proof — a correlational signal, held out from narration generation and given only to the
verification gate (services/narration/graph.py's covariation_check node) to check a narrated
mechanism claim against.

Spearman (rank) correlation, not Pearson: no reason to assume a linear driver/yield relationship.
Implemented directly on numpy (no scipy dependency — consistent with this pipeline's minimal-
dependency discipline; see pipeline/requirements-lookup.txt's own reasoning), with real
average-rank tie handling — not a shortcut: an early version used a plain double-argsort with no
tie correction, which silently broke on any constant/near-constant field (a near-uniform
temperature patch, a region with few distinct precipitation values) — a naive rank of a constant
array isn't itself constant, it's an arbitrary permutation from the sort's own tie-breaking order,
which can spuriously correlate with anything monotonic. Caught by this module's own test suite
(test_process_covariation.py) before this ever ran against real data, not discovered later.
"""

import numpy as np
import xarray as xr

# The region-cell-count floor below which a covariation result is still computed and logged, but
# not trusted to gate a retry — the same small-n caution drift_stats.py already discloses for its
# own statistical test (n=25, current baseline), applied here where region size varies per query
# (a subcontinent query has real statistical power; a small state/province query may not).
MIN_CELLS_FOR_CONFIDENCE = 15


def _rank(values: np.ndarray) -> np.ndarray:
    """Average rank, ties included — e.g. [10, 20, 20, 30] -> [0, 1.5, 1.5, 3]. Mergesort (stable)
    so equal values sort in a fixed, reproducible order before being collapsed to their shared
    average rank — an unstable sort would still get the same average-rank result here, but stable
    ordering makes the intermediate steps of this function reproducible to reason about."""
    sorter = np.argsort(values, kind="mergesort")
    sorted_values = values[sorter]
    ranks_in_sorted_order = np.arange(len(values), dtype=float)

    i = 0
    while i < len(sorted_values):
        j = i
        while j + 1 < len(sorted_values) and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        if j > i:
            ranks_in_sorted_order[i : j + 1] = (i + j) / 2.0
        i = j + 1

    ranks = np.empty_like(ranks_in_sorted_order)
    ranks[sorter] = ranks_in_sorted_order
    return ranks


def spearman_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman's rho between two equal-length 1D arrays with no NaNs — see driver_covariation()
    for the real NaN-masking step this assumes already happened."""
    if len(a) != len(b):
        raise ValueError(f"arrays must be the same length, got {len(a)} and {len(b)}")
    if len(a) < 2:
        raise ValueError("need at least 2 cells to compute a correlation")
    ra, rb = _rank(np.asarray(a, dtype=float)), _rank(np.asarray(b, dtype=float))
    if np.std(ra) == 0 or np.std(rb) == 0:
        return 0.0  # a constant field has no real correlation with anything, not undefined
    return float(np.corrcoef(ra, rb)[0, 1])


def driver_covariation(driver_grids: dict[str, xr.DataArray], yield_grid: xr.DataArray) -> dict[str, dict]:
    """For each driver grid, the Spearman correlation between its per-cell values and the yield
    grid's per-cell values, over the region's cells — masked to cells where the yield grid has a
    real value (LPJmL's own output is null outside where a crop is actually grown; see
    frontend/src/precomputedFetch.ts's applyCropMask for the client-side counterpart of the same
    real gap). Returns, per driver key: {"r": float | None, "cell_count": int,
    "low_confidence": bool} — ranking by |r| and deciding what to do with the result is the
    caller's job (services/narration/graph.py's covariation_check node); this function only
    computes.
    """
    yield_values = np.asarray(yield_grid.values, dtype=float).flatten()
    valid_mask = ~np.isnan(yield_values)

    result = {}
    for driver_name, driver_grid in driver_grids.items():
        driver_values = np.asarray(driver_grid.values, dtype=float).flatten()
        if driver_values.shape != yield_values.shape:
            raise ValueError(
                f"{driver_name!r} grid shape {driver_values.shape} does not match the yield grid "
                f"shape {yield_values.shape} — both must come from the same (lon, lat, radius)"
            )
        combined_mask = valid_mask & ~np.isnan(driver_values)
        n = int(combined_mask.sum())
        if n < 2:
            result[driver_name] = {"r": None, "cell_count": n, "low_confidence": True}
            continue
        r = spearman_correlation(driver_values[combined_mask], yield_values[combined_mask])
        result[driver_name] = {"r": r, "cell_count": n, "low_confidence": n < MIN_CELLS_FOR_CONFIDENCE}
    return result
