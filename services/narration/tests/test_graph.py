"""Tests against graph.py's own structure and routing — narrate.py's tests (test_narrate.py)
already cover the end-to-end behavior through the public narrate() contract; these test the graph
itself: its node set and its conditional routing logic, independent of that wrapper."""

from graph import MAX_RETRIES, _route_after_guard_numbers, _route_after_verify, _select_top_driver, compiled_graph, run_narration_graph

CLIMATE_EVIDENCE = {
    "temp_change_c": 1.8,
    "precip_change_pct": -12.0,
    "extreme_heat_days": 6,
    "consecutive_dry_days": 4,
}

# Deliberately confident (cell_count above covariation.py's MIN_CELLS_FOR_CONFIDENCE) so existing
# tests exercise the real "a top driver was found" path, not the "region too small to check" path.
DRIVER_COVARIATION = {
    "temp_change_c": {"r": 0.4, "cell_count": 20, "low_confidence": False},
    "precip_change_pct": {"r": -0.3, "cell_count": 20, "low_confidence": False},
    "extreme_heat_days": {"r": 0.9, "cell_count": 20, "low_confidence": False},
    "consecutive_dry_days": {"r": 0.5, "cell_count": 20, "low_confidence": False},
}

PASS_VERIFICATION = {"result": "PASS", "direction_match": True, "unsupported_claims": [], "contradictions": [], "confidence": 0.8}
FAIL_VERIFICATION = {"result": "FAIL", "direction_match": False, "unsupported_claims": [], "contradictions": ["disagrees"], "confidence": 0.5}


class _ScriptedModelClient:
    def __init__(self, generate_responses, verify_responses):
        self._generate_responses = list(generate_responses)
        self._verify_responses = list(verify_responses)

    def generate(self, prompt: str) -> str:
        return self._generate_responses.pop(0)

    def verify(self, prompt: str) -> dict:
        return self._verify_responses.pop(0)


def _run(generate_responses, verify_responses, driver_covariation=DRIVER_COVARIATION):
    model_client = _ScriptedModelClient(generate_responses, verify_responses)
    return run_narration_graph(
        model_client, "Iowa", "maize", 2.0, CLIMATE_EVIDENCE, -12.3, literature=[], driver_covariation=driver_covariation
    )


def test_graph_has_exactly_the_four_real_nodes():
    # generate, guard_numbers, covariation_check, verify, plus LangGraph's own implicit
    # start/end — no extra nodes accumulated by accident.
    assert set(compiled_graph.get_graph().nodes) - {"__start__", "__end__"} == {
        "generate", "guard_numbers", "covariation_check", "verify",
    }


def test_route_after_verify_sends_pass_to_end():
    from langgraph.graph import END
    assert _route_after_verify({"status": "PASS"}) == END


def test_route_after_verify_sends_fail_with_retries_left_back_to_generate():
    assert _route_after_verify({"status": "FAIL"}) == "generate"


def test_route_after_verify_sends_scientific_disagreement_to_end():
    from langgraph.graph import END
    assert _route_after_verify({"status": "SCIENTIFIC_DISAGREEMENT"}) == END


def test_route_after_guard_numbers_sends_a_pass_to_covariation_check():
    state = {"number_guard": {"passed": True, "unsupported_numbers": []}, "status": None}
    assert _route_after_guard_numbers(state) == "covariation_check"


def test_route_after_guard_numbers_sends_a_fail_with_retries_left_back_to_generate():
    state = {"number_guard": {"passed": False, "unsupported_numbers": [42.0]}, "status": None}
    assert _route_after_guard_numbers(state) == "generate"


def test_route_after_guard_numbers_sends_exhausted_fail_to_end():
    from langgraph.graph import END
    state = {"number_guard": {"passed": False, "unsupported_numbers": [42.0]}, "status": "SCIENTIFIC_DISAGREEMENT"}
    assert _route_after_guard_numbers(state) == END


def test_select_top_driver_picks_the_strongest_confident_correlation():
    result = _select_top_driver(DRIVER_COVARIATION)
    assert result == {"checked": True, "top_driver": "extreme_heat_days", "top_r": 0.9}


def test_select_top_driver_ignores_low_confidence_drivers():
    covariation = {
        "temp_change_c": {"r": 0.99, "cell_count": 3, "low_confidence": True},  # strongest r, too few cells
        "precip_change_pct": {"r": 0.4, "cell_count": 20, "low_confidence": False},
    }
    result = _select_top_driver(covariation)
    assert result["top_driver"] == "precip_change_pct"


def test_select_top_driver_reports_unchecked_when_nothing_is_confident():
    covariation = {"temp_change_c": {"r": None, "cell_count": 1, "low_confidence": True}}
    assert _select_top_driver(covariation) == {"checked": False, "top_driver": None, "top_r": None}


def test_full_graph_run_passes_on_first_attempt():
    final_state = _run(
        generate_responses=["Yields are likely to decline modestly."],
        verify_responses=[PASS_VERIFICATION],
    )
    assert final_state["status"] == "PASS"
    assert final_state["attempt"] == 1
    assert final_state["number_guard"]["passed"] is True
    assert final_state["covariation_result"]["top_driver"] == "extreme_heat_days"


def test_full_graph_run_retries_the_real_max_number_of_times_then_disagrees():
    final_state = _run(
        generate_responses=["Attempt 1.", "Attempt 2.", "Attempt 3."],
        verify_responses=[FAIL_VERIFICATION, FAIL_VERIFICATION, FAIL_VERIFICATION],
    )
    assert final_state["status"] == "SCIENTIFIC_DISAGREEMENT"
    assert final_state["attempt"] == MAX_RETRIES + 1


def test_a_fabricated_number_retries_without_spending_a_verify_call():
    model_client = _ScriptedModelClient(
        generate_responses=["Yields could fall by 42%.", "Yields are likely to decline modestly."],
        verify_responses=[PASS_VERIFICATION],  # only one response — a second verify() call would raise IndexError
    )
    final_state = run_narration_graph(
        model_client, "Iowa", "maize", 2.0, CLIMATE_EVIDENCE, -12.3, literature=[], driver_covariation=DRIVER_COVARIATION
    )
    assert final_state["status"] == "PASS"
    assert final_state["attempt"] == 2  # the first, fabricated attempt was retried before verify ever ran


def test_a_fabricated_number_still_exhausted_reports_scientific_disagreement():
    final_state = _run(
        generate_responses=["Yields could fall by 42%.", "Yields could fall by 43%.", "Yields could fall by 44%."],
        verify_responses=[],  # verify() is never reached — an empty script proves it
    )
    assert final_state["status"] == "SCIENTIFIC_DISAGREEMENT"
    assert final_state["attempt"] == MAX_RETRIES + 1
    assert final_state["number_guard"]["passed"] is False


def test_a_flagged_mechanism_inconsistency_triggers_a_retry_like_any_other_fail():
    mechanism_mismatch = {**PASS_VERIFICATION, "mechanism_consistent": False}
    final_state = _run(
        generate_responses=["Heat stress during flowering drives the decline.", "Water stress drives the decline."],
        verify_responses=[mechanism_mismatch, PASS_VERIFICATION],
    )
    assert final_state["status"] == "PASS"
    assert final_state["attempt"] == 2


def test_a_query_with_no_confident_driver_still_completes_normally():
    unconfident = {"temp_change_c": {"r": None, "cell_count": 1, "low_confidence": True}}
    final_state = _run(
        generate_responses=["Yields are likely to decline modestly."],
        verify_responses=[PASS_VERIFICATION],
        driver_covariation=unconfident,
    )
    assert final_state["status"] == "PASS"
    assert final_state["covariation_result"]["checked"] is False
