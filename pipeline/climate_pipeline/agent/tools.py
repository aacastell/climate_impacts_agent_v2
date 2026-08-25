"""ADR-005's tools, built as they become real — starting with geocode().

geocode() is deliberately thin: it calls Amazon Location Service (Esri-backed — verified live
against real region names, including physical-feature ones like "Mekong Delta", see
conversation/commit history) and returns the raw candidate list, unranked beyond what Esri itself
returns. It does NOT pick a candidate. Picking among ambiguous candidates (e.g. "Mekong Delta"
resolving to the real Vietnamese delta, an unrelated German restaurant, or a coincidentally-named
Indonesian sub-district) is exactly the kind of ambiguity-diagnosis-and-recovery ADR-005 Step 4
calls genuinely agentic — it needs understanding(), which isn't built yet. Faking that selection
with a hardcoded heuristic here would just be a disguised stub, the thing this project explicitly
moved away from.

Real, verified finding this tool's shape is built around: Esri's own top-ranked result is not
reliably the best one. "Ganges Delta" returns one clean, well-tagged candidate
(SupplementalCategories: ["Delta"]). "Mekong Delta" returns three: the top-ranked candidate has no
category at all, the second is an unrelated restaurant in Germany, and the third — not the
top-ranked one — carries SupplementalCategories: ["Delta"]. A caller that only looked at the top
result would get Mekong Delta wrong.
"""


def geocode(location_client, index_name: str, region_text: str, max_results: int = 5) -> list[dict]:
    """Real Amazon Location Service call, real candidates, no selection. Each candidate:
    {label, lon, lat, categories, supplemental_categories, relevance} — categories and
    supplemental_categories are None when Esri returns nothing for that candidate (a real,
    common case, not an error — see module docstring)."""
    response = location_client.search_place_index_for_text(
        IndexName=index_name, Text=region_text, MaxResults=max_results
    )
    candidates = []
    for result in response["Results"]:
        place = result["Place"]
        lon, lat = place["Geometry"]["Point"]
        candidates.append(
            {
                "label": place["Label"],
                "lon": lon,
                "lat": lat,
                "categories": place.get("Categories"),
                "supplemental_categories": place.get("SupplementalCategories"),
                "relevance": result["Relevance"],
            }
        )
    return candidates
