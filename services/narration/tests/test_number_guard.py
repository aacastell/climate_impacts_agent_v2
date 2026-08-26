from number_guard import check_number_provenance

CLIMATE_EVIDENCE = {
    "temp_change_c": 1.8,
    "precip_change_pct": -12.0,
    "extreme_heat_days": 6,
    "consecutive_dry_days": 4,
}
LITERATURE = [{"text": "Heat stress above 35C during flowering can cut kernel set by 15%.", "source": "test-source"}]


def test_passes_when_every_number_traces_to_climate_evidence():
    narration = "Temperatures are expected to rise by about 1.8C, with 6 more extreme heat days."
    result = check_number_provenance(narration, CLIMATE_EVIDENCE, [], warming_level_c=2.0)
    assert result["passed"] is True
    assert result["unsupported_numbers"] == []


def test_passes_when_a_number_traces_to_the_warming_level_itself():
    # warming_level_c isn't in climate_evidence — it has to be an allowed source on its own, or
    # every narration that restates "at 2C of warming" (nearly all of them) would false-positive.
    narration = "At 2 degrees of warming, conditions worsen."
    result = check_number_provenance(narration, CLIMATE_EVIDENCE, [], warming_level_c=2.0)
    assert result["passed"] is True


def test_passes_when_a_number_traces_to_retrieved_literature():
    narration = "Literature suggests kernel set can fall by 15% under this kind of heat stress."
    result = check_number_provenance(narration, CLIMATE_EVIDENCE, LITERATURE, warming_level_c=2.0)
    assert result["passed"] is True


def test_flags_a_number_with_no_source_anywhere():
    narration = "Yields are expected to fall by 42%."
    result = check_number_provenance(narration, CLIMATE_EVIDENCE, LITERATURE, warming_level_c=2.0)
    assert result["passed"] is False
    assert result["unsupported_numbers"] == [42.0]


def test_allows_narration_to_round_within_tolerance():
    narration = "Precipitation falls by about 12%."  # source is -12.0; sign/precision differ, still real
    result = check_number_provenance(narration, CLIMATE_EVIDENCE, [], warming_level_c=2.0)
    assert result["passed"] is True


def test_a_narration_with_no_numbers_at_all_always_passes():
    result = check_number_provenance("Conditions are expected to worsen modestly.", CLIMATE_EVIDENCE, [], warming_level_c=2.0)
    assert result["passed"] is True
    assert result["unsupported_numbers"] == []
