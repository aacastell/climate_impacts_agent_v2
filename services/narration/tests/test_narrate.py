from narrate import narrate

CLIMATE_EVIDENCE = {
    "temp_change_c": 1.8,
    "precip_change_pct": -12.0,
    "extreme_heat_days": 6,
    "consecutive_dry_days": 4,
}


class _ScriptedModelClient:
    """Records every prompt it's given (real regression guard: generation must never see the
    yield number) and returns pre-scripted responses in sequence."""

    def __init__(self, generate_responses, verify_responses):
        self._generate_responses = list(generate_responses)
        self._verify_responses = list(verify_responses)
        self.generate_prompts = []
        self.verify_prompts = []

    def generate(self, prompt: str) -> str:
        self.generate_prompts.append(prompt)
        return self._generate_responses.pop(0)

    def verify(self, prompt: str) -> dict:
        self.verify_prompts.append(prompt)
        return self._verify_responses.pop(0)


def _fake_retrieve(query: str):
    return [{"text": "Heat stress during flowering reduces kernel set.", "source": "test-source"}]


def test_narrate_passes_on_first_attempt():
    model_client = _ScriptedModelClient(
        generate_responses=["Yields are likely to decline modestly under these conditions."],
        verify_responses=[{"result": "PASS", "direction_match": True, "unsupported_claims": [], "contradictions": [], "confidence": 0.8}],
    )

    result = narrate(model_client, _fake_retrieve, "Iowa", "maize", 2.0, CLIMATE_EVIDENCE, -12.3)

    assert result["status"] == "PASS"
    assert result["attempts"] == 1
    assert "decline modestly" in result["narration"]


def test_generation_prompt_never_contains_the_yield_number():
    # Real regression guard for ADR-007's core requirement: generation must be blind.
    model_client = _ScriptedModelClient(
        generate_responses=["Some narration text."],
        verify_responses=[{"result": "PASS", "direction_match": True, "unsupported_claims": [], "contradictions": [], "confidence": 0.9}],
    )

    narrate(model_client, _fake_retrieve, "Iowa", "maize", 2.0, CLIMATE_EVIDENCE, -37.5)

    assert "-37.5" not in model_client.generate_prompts[0]
    assert "37.5" not in model_client.generate_prompts[0]


def test_verification_prompt_does_contain_the_yield_number():
    model_client = _ScriptedModelClient(
        generate_responses=["Some narration text."],
        verify_responses=[{"result": "PASS", "direction_match": True, "unsupported_claims": [], "contradictions": [], "confidence": 0.9}],
    )

    narrate(model_client, _fake_retrieve, "Iowa", "maize", 2.0, CLIMATE_EVIDENCE, -37.5)

    assert "-37.5" in model_client.verify_prompts[0]


def test_narrate_retries_on_fail_then_passes():
    model_client = _ScriptedModelClient(
        generate_responses=["First attempt narration.", "Second attempt narration."],
        verify_responses=[
            {"result": "FAIL", "direction_match": False, "unsupported_claims": ["wrong direction"], "contradictions": [], "confidence": 0.6},
            {"result": "PASS", "direction_match": True, "unsupported_claims": [], "contradictions": [], "confidence": 0.85},
        ],
    )

    result = narrate(model_client, _fake_retrieve, "Iowa", "maize", 2.0, CLIMATE_EVIDENCE, -12.3)

    assert result["status"] == "PASS"
    assert result["attempts"] == 2
    assert result["narration"] == "Second attempt narration."


def test_narrate_reports_scientific_disagreement_after_exhausting_retries():
    fail = {"result": "FAIL", "direction_match": False, "unsupported_claims": [], "contradictions": ["disagrees with projection"], "confidence": 0.5}
    model_client = _ScriptedModelClient(
        generate_responses=["Attempt 1.", "Attempt 2.", "Attempt 3."],
        verify_responses=[fail, fail, fail],
    )

    result = narrate(model_client, _fake_retrieve, "Iowa", "maize", 2.0, CLIMATE_EVIDENCE, -12.3)

    # Not AGENT_FAILURE — a distinct, typed state, per ADR-007 Step 4.
    assert result["status"] == "SCIENTIFIC_DISAGREEMENT"
    assert result["attempts"] == 3
    assert result["verification"]["result"] == "FAIL"


def test_narrate_includes_retrieved_literature_in_the_result_for_eval_capture():
    model_client = _ScriptedModelClient(
        generate_responses=["Narration."],
        verify_responses=[{"result": "PASS", "direction_match": True, "unsupported_claims": [], "contradictions": [], "confidence": 0.8}],
    )

    result = narrate(model_client, _fake_retrieve, "Iowa", "maize", 2.0, CLIMATE_EVIDENCE, -12.3)

    assert result["literature"] == [{"text": "Heat stress during flowering reduces kernel set.", "source": "test-source"}]
