import pytest

from climate_pipeline.agent.tools import crop, geocode, timecode

# Real response shapes captured this session against Amazon Location Service (Esri-backed),
# not invented — see tools.py's module docstring. Mekong Delta's real response demonstrates
# exactly why this tool doesn't pick a candidate: the top-ranked result has no category at all,
# the second is an unrelated restaurant in Germany, and the third (not top-ranked) is the one
# actually tagged as a delta.
MEKONG_DELTA_RESPONSE = {
    "Results": [
        {
            "Place": {"Label": "Mekong Delta, VNM", "Geometry": {"Point": [105.83224, 10.01211]}},
            "Relevance": 1.0,
        },
        {
            "Place": {
                "Label": "Mekong Delta, Berger Vorstadt 29, 86609, Donauwörth, Bayern, DEU",
                "Geometry": {"Point": [10.778388, 48.723914]},
                "Categories": ["PointOfInterestType"],
                "SupplementalCategories": ["Southeast Asian Food"],
            },
            "Relevance": 1.0,
        },
        {
            "Place": {
                "Label": "Mekong Delta, VNM",
                "Geometry": {"Point": [106.66667, 10.33333]},
                "Categories": ["PointOfInterestType"],
                "SupplementalCategories": ["Delta"],
            },
            "Relevance": 1.0,
        },
    ]
}

GANGES_DELTA_RESPONSE = {
    "Results": [
        {
            "Place": {
                "Label": "Ganges Delta, BGD",
                "Geometry": {"Point": [89.5, 22.5]},
                "Categories": ["PointOfInterestType"],
                "SupplementalCategories": ["Delta"],
            },
            "Relevance": 1.0,
        }
    ]
}


class _FakeLocationClient:
    def __init__(self, response: dict):
        self.response = response
        self.calls = []

    def search_place_index_for_text(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_geocode_returns_every_candidate_with_no_selection():
    client = _FakeLocationClient(MEKONG_DELTA_RESPONSE)

    candidates = geocode(client, "test-index", "Mekong Delta", max_results=5)

    assert len(candidates) == 3
    assert client.calls == [{"IndexName": "test-index", "Text": "Mekong Delta", "MaxResults": 5}]


def test_geocode_extracts_lon_lat_from_the_point_geometry():
    client = _FakeLocationClient(MEKONG_DELTA_RESPONSE)
    candidates = geocode(client, "test-index", "Mekong Delta")
    assert candidates[0]["lon"] == 105.83224
    assert candidates[0]["lat"] == 10.01211


def test_geocode_preserves_categories_where_present_and_none_where_absent():
    client = _FakeLocationClient(MEKONG_DELTA_RESPONSE)
    candidates = geocode(client, "test-index", "Mekong Delta")

    # Real finding this test locks in: the top-ranked candidate has no category data at all.
    assert candidates[0]["categories"] is None
    assert candidates[0]["supplemental_categories"] is None

    # The actually-correct candidate (a real delta) is third, not first.
    assert candidates[2]["supplemental_categories"] == ["Delta"]


def test_geocode_does_not_reorder_or_filter_candidates():
    client = _FakeLocationClient(MEKONG_DELTA_RESPONSE)
    candidates = geocode(client, "test-index", "Mekong Delta")
    # Order matches Esri's own response order — this tool doesn't rank or select.
    assert candidates[0]["label"] == "Mekong Delta, VNM"
    assert "Donauwörth" in candidates[1]["label"]
    assert candidates[2]["supplemental_categories"] == ["Delta"]


def test_geocode_handles_a_single_clean_result():
    client = _FakeLocationClient(GANGES_DELTA_RESPONSE)
    candidates = geocode(client, "test-index", "Ganges Delta")
    assert len(candidates) == 1
    assert candidates[0]["supplemental_categories"] == ["Delta"]


def test_crop_matches_synonyms():
    assert crop("How will corn do?") == "maize"
    assert crop("What about soybeans?") == "soy"


def test_crop_prefers_spring_wheat_over_bare_wheat():
    assert crop("spring wheat yields") == "spring_wheat"


def test_crop_returns_none_for_an_unsupported_crop():
    assert crop("How will barley do?") is None


def test_timecode_finds_the_closest_table_entry():
    table = [{"gwl_c": 1.5, "year": 2030}, {"gwl_c": 2.1, "year": 2045}, {"gwl_c": 3.0, "year": 2060}]
    assert timecode(table, 2.0) == 2045
    assert timecode(table, 1.4) == 2030


def test_timecode_raises_on_an_empty_table():
    with pytest.raises(ValueError, match="empty"):
        timecode([], 2.0)
