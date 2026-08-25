"""Tests against graph.py's own structure and routing — narrate.py's tests (test_narrate.py)
already cover the end-to-end behavior through the public narrate() contract; these test the graph
itself: its node set and its conditional routing logic, independent of that wrapper."""

from graph import MAX_RETRIES, _route_after_verify, compiled_graph, run_narration_graph

CLIMATE_EVIDENCE = {
    "temp_change_c": 1.8,
    "precip_change_pct": -12.0,
    "extreme_heat_days": 6,
    "consecutive_dry_days": 4,
}


class _ScriptedModelClient:
    def __init__(self, generate_responses, verify_responses):
        self._generate_responses = list(generate_responses)
        self._verify_responses = list(verify_responses)

    def generate(self, prompt: str) -> str:
        return self._generate_responses.pop(0)

    def verify(self, prompt: str) -> dict:
        return self._verify_responses.pop(0)


def test_graph_has_exactly_the_two_real_nodes():
    # generate and verify, plus LangGraph's own implicit start/end — no extra nodes accumulated
    # by accident during the rewrite from the plain loop.
    assert set(compiled_graph.get_graph().nodes) - {"__start__", "__end__"} == {"generate", "verify"}


def test_route_after_verify_sends_pass_to_end():
    from langgraph.graph import END
    assert _route_after_verify({"status": "PASS"}) == END


def test_route_after_verify_sends_fail_with_retries_left_back_to_generate():
    assert _route_after_verify({"status": "FAIL"}) == "generate"


def test_route_after_verify_sends_scientific_disagreement_to_end():
    from langgraph.graph import END
    assert _route_after_verify({"status": "SCIENTIFIC_DISAGREEMENT"}) == END


def test_full_graph_run_passes_on_first_attempt():
    model_client = _ScriptedModelClient(
        generate_responses=["Yields are likely to decline modestly."],
        verify_responses=[{"result": "PASS", "direction_match": True, "unsupported_claims": [], "contradictions": [], "confidence": 0.8}],
    )
    final_state = run_narration_graph(model_client, "Iowa", "maize", 2.0, CLIMATE_EVIDENCE, -12.3, literature=[])
    assert final_state["status"] == "PASS"
    assert final_state["attempt"] == 1


def test_full_graph_run_retries_the_real_max_number_of_times_then_disagrees():
    fail = {"result": "FAIL", "direction_match": False, "unsupported_claims": [], "contradictions": ["disagrees"], "confidence": 0.5}
    model_client = _ScriptedModelClient(
        generate_responses=["Attempt 1.", "Attempt 2.", "Attempt 3."],
        verify_responses=[fail, fail, fail],
    )
    final_state = run_narration_graph(model_client, "Iowa", "maize", 2.0, CLIMATE_EVIDENCE, -12.3, literature=[])
    assert final_state["status"] == "SCIENTIFIC_DISAGREEMENT"
    assert final_state["attempt"] == MAX_RETRIES + 1
