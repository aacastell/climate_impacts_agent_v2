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

crop() and timecode() are different in kind from geocode(): both resolve against a small, fixed,
deliberately bounded real vocabulary (the four crops this system actually supports; the 67 real
computed GWL windows process_field produces), not an open-ended external one — so, unlike
geocode(), there's no ambiguous candidate set requiring the agent's judgment. A plain deterministic
lookup is the correct, permanent shape here, not a stand-in for something bigger.
"""

# The four crops this system supports (README Scope) — a real, deliberate scientific scope
# decision (LPJmL's actual model coverage), not a placeholder the way the old 5 demo regions were.
CROP_KEYWORDS = {
    "maize": "maize",
    "corn": "maize",
    "spring wheat": "spring_wheat",
    "wheat": "spring_wheat",
    "soybeans": "soy",
    "soybean": "soy",
    "soy": "soy",
    "rice": "rice",
}


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


def crop(question: str) -> str | None:
    """Resolves a free-text question to one of the four supported crops, or None. Longest keyword
    first so "spring wheat" matches before the bare "wheat" fallback."""
    lower = question.lower()
    for keyword in sorted(CROP_KEYWORDS, key=len, reverse=True):
        if keyword in lower:
            return CROP_KEYWORDS[keyword]
    return None


def timecode(gwl_year_table: list[dict], target_gwl_c: float) -> int:
    """gwl(target) -> year: table[gwl] -> timewindow (ADR-005), against the real 67-entry table
    process_field's tas/heat_days units produce (get_or_compute_gwl_year_table). A literal query
    float essentially never exactly equals one of the table's real computed gwl_c values (e.g.
    1.973, 2.041, ...), so this resolves to the entry closest by absolute difference — still a
    plain deterministic table scan, not an LLM judgment call.

    gwl_year_table: the real list of {"gwl_c": float, "year": int} entries from
    processed/global/gwl_year_table.json.
    """
    if not gwl_year_table:
        raise ValueError("gwl_year_table is empty — nothing to look up against")
    closest = min(gwl_year_table, key=lambda entry: abs(entry["gwl_c"] - target_gwl_c))
    return closest["year"]
