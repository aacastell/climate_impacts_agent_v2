from orchestrator import interpret

GWL_YEAR_TABLE = [{"gwl_c": 1.5, "year": 2030}, {"gwl_c": 2.1, "year": 2045}, {"gwl_c": 3.0, "year": 2060}]


class _FakeLocationClient:
    def __init__(self, response: dict):
        self.response = response
        self.calls = []

    def search_place_index_for_text(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _ScriptedModelClient:
    """Returns a pre-scripted sequence of Bedrock Converse-shaped assistant messages, one per
    call, regardless of what conversation state it's actually given — real orchestration logic
    under test, fake model behind it."""

    def __init__(self, scripted_messages: list[dict]):
        self._messages = list(scripted_messages)
        self.calls = []

    def resolve_tool_call(self, messages, tools, system_prompt):
        self.calls.append({"messages": [m for m in messages], "tools": tools, "system_prompt": system_prompt})
        return self._messages.pop(0)


def _tool_use_message(name: str, tool_use_id: str, input_: dict) -> dict:
    return {"role": "assistant", "content": [{"toolUse": {"toolUseId": tool_use_id, "name": name, "input": input_}}]}


def test_interpret_resolves_end_to_end_through_real_tool_execution():
    location_response = {
        "Results": [
            {"Place": {"Label": "Iowa, USA", "Geometry": {"Point": [-93.5, 42.0]}}, "Relevance": 1.0}
        ]
    }
    location_client = _FakeLocationClient(location_response)

    scripted = [
        _tool_use_message("geocode", "t1", {"region_text": "Iowa"}),
        _tool_use_message("crop", "t2", {"question": "How will maize yields in Iowa change at 2C?"}),
        _tool_use_message("timecode", "t3", {"warming_level_c": 2.0}),
        _tool_use_message(
            "resolved",
            "t4",
            {
                "region_name": "Iowa",
                "region_lon": -93.5,
                "region_lat": 42.0,
                "crop": "maize",
                "warming_level_c": 2.0,
                "year": 2045,
            },
        ),
    ]
    model_client = _ScriptedModelClient(scripted)

    result = interpret(
        model_client,
        location_client,
        "test-index",
        GWL_YEAR_TABLE,
        "How will maize yields in Iowa change at 2C?",
    )

    assert result == {
        "kind": "resolved",
        "region": {"name": "Iowa", "lon": -93.5, "lat": 42.0},
        "crop": "maize",
        "warmingLevelC": 2.0,
        "year": 2045,
    }
    # Real tools were actually invoked, not stubbed — geocode really called the location client.
    assert location_client.calls == [{"IndexName": "test-index", "Text": "Iowa", "MaxResults": 5}]
    assert len(model_client.calls) == 4


def test_interpret_returns_clarify_without_calling_more_tools():
    model_client = _ScriptedModelClient(
        [_tool_use_message("clarify", "t1", {"question": "Did you mean the Vietnamese Mekong Delta?"})]
    )

    result = interpret(model_client, _FakeLocationClient({"Results": []}), "test-index", GWL_YEAR_TABLE, "What about Mekong?")

    assert result == {
        "kind": "clarify",
        "question": "Did you mean the Vietnamese Mekong Delta?",
        "tool_use_id": "t1",
    }
    assert len(model_client.calls) == 1


def test_interpret_resumes_a_clarify_round_trip_from_a_stored_trace():
    # Real regression guard for the query_id/short-lived-store design ADR-005 names — a resumed
    # call must NOT re-add the original question (it's already in the stored trace) and the
    # caller's appended toolResult for the pending clarify call must reach the model as the very
    # next turn, per Bedrock's real toolUse/toolResult pairing requirement.
    stored_trace = [
        {"role": "user", "content": [{"text": "What about Mekong?"}]},
        _tool_use_message("clarify", "t1", {"question": "Did you mean the Vietnamese Mekong Delta?"}),
        # The caller (api/interpret_handler.py in production) appends this before resuming —
        # the user's clarifying answer, shaped as the toolResult for the pending clarify call.
        {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "content": [{"text": "Yes, the Vietnamese one."}]}}]},
    ]
    scripted = [
        _tool_use_message("geocode", "t2", {"region_text": "Mekong Delta, Vietnam"}),
        {"role": "assistant", "content": [{"text": "still thinking"}]},
    ]
    model_client = _ScriptedModelClient(scripted)
    location_client = _FakeLocationClient({"Results": [{"Place": {"Label": "Mekong Delta, VNM", "Geometry": {"Point": [106.6, 10.3]}}, "Relevance": 1.0}]})
    # trace is mutated in place by interpret() (it IS `messages`) — snapshot before calling,
    # since comparing against stored_trace afterward would compare against its own final state.
    expected_first_call = list(stored_trace)

    result = interpret(
        model_client, location_client, "test-index", GWL_YEAR_TABLE,
        "this question is ignored on resume", trace=stored_trace,
    )

    # The model's very first call on resume sees the full stored history, unmodified — no
    # duplicate question re-appended.
    first_call_messages = model_client.calls[0]["messages"]
    assert first_call_messages == expected_first_call
    assert result["kind"] == "refusal"  # scripted response doesn't reach a resolution; irrelevant to what this test checks


def test_interpret_refuses_when_model_never_reaches_a_resolution():
    model_client = _ScriptedModelClient([{"role": "assistant", "content": [{"text": "I'm not sure how to help."}]}])

    result = interpret(model_client, _FakeLocationClient({"Results": []}), "test-index", GWL_YEAR_TABLE, "asdf")

    assert result["kind"] == "refusal"
    assert result["reason"] == "no_resolution"


def test_interpret_passes_geocode_candidates_back_to_the_model_for_judgment():
    # Real regression guard for the actual reason this tool doesn't pick a candidate itself (see
    # agent/tools.py) — the orchestrator must feed the full, unranked candidate list back to the
    # model as a tool result, not silently pick candidates[0].
    location_response = {
        "Results": [
            {"Place": {"Label": "Mekong Delta, Restaurant, DEU", "Geometry": {"Point": [10.7, 48.7]}}, "Relevance": 1.0},
            {
                "Place": {
                    "Label": "Mekong Delta, VNM",
                    "Geometry": {"Point": [106.6, 10.3]},
                    "SupplementalCategories": ["Delta"],
                },
                "Relevance": 1.0,
            },
        ]
    }
    location_client = _FakeLocationClient(location_response)

    scripted = [
        _tool_use_message("geocode", "t1", {"region_text": "Mekong Delta"}),
        {"role": "assistant", "content": [{"text": "still thinking"}]},
    ]
    model_client = _ScriptedModelClient(scripted)

    interpret(model_client, location_client, "test-index", GWL_YEAR_TABLE, "rice near the Mekong Delta")

    second_call_messages = model_client.calls[1]["messages"]
    tool_result_message = second_call_messages[-1]
    # Wrapped under "candidates", not a bare list — Bedrock Converse requires toolResult.content[]
    # .json to be a JSON object, confirmed via a real live call that got past every other issue.
    tool_result_json = tool_result_message["content"][0]["toolResult"]["content"][0]["json"]
    candidates_seen_by_model = tool_result_json["candidates"]
    assert len(candidates_seen_by_model) == 2
    assert candidates_seen_by_model[1]["supplemental_categories"] == ["Delta"]
