"""The 5 demo regions this system currently supports.

Must match frontend/src/api/mockClient.ts's KNOWN_REGIONS exactly (name, lon, lat). No shared
build step exists between this Python pipeline and the TypeScript frontend, so this is a
deliberate duplication with a cross-reference — same pattern already used for CROPS in
fetch/agriculture.py ("Same crop vocabulary as frontend's Crop type").

Precomputing directly for this fixed, small region set is an explicit, temporary narrowing of
ADR-006 Step 3's own reasoning (regional aggregation should stay query-time because the region
vocabulary is unbounded) — valid only because there's no free-text region resolver yet, just 5
hardcoded names. Revisit once one exists; see pipeline/README.md.
"""

REGIONS: dict[str, dict] = {
    "occitanie": {"name": "Occitanie", "lon": 2.15, "lat": 43.6},
    "iowa": {"name": "Iowa", "lon": -93.6, "lat": 42.0},
    "punjab": {"name": "Punjab", "lon": 75.3, "lat": 31.1},
    "nile_delta": {"name": "Nile Delta", "lon": 31.0, "lat": 30.8},
    "mekong_delta": {"name": "Mekong Delta", "lon": 105.8, "lat": 10.0},
}
