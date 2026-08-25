"""ADR-007's generate/verify/retry flow as a real LangGraph graph — not a wrapper around the
plain loop that used to live in narrate.py, an actual replacement of it.

Why this one, specifically, and not understanding()'s tool-calling loop (see ADR-009): this is a
genuine fit for a graph abstraction, not a forced one. The retry logic here branches between
three real outcomes (PASS, retry, and a distinct SCIENTIFIC_DISAGREEMENT terminal state once
retries are exhausted — ADR-007 Step 4) coordinated across two separate model calls with
different visibility into the same held-out number. That's real multi-node, multi-terminal-state
branching between distinct functions — exactly what generate->verify->self-correct loops are the
standard, legitimate LangGraph pattern for. understanding()'s loop, by contrast, branches inside
a single model turn's own tool-selection reasoning, not between named Python functions — there's
nothing for a graph to coordinate that the model isn't already coordinating itself.

State intentionally carries model_client/retrieve_fn as plain objects, not serialized handles —
this graph is compiled and run in-process per request, never checkpointed or persisted across a
process boundary, so there's no requirement that state be JSON-serializable.
"""

from typing import TypedDict

from langgraph.graph import END, StateGraph

MAX_RETRIES = 2  # total attempts = MAX_RETRIES + 1, matching narrate.py's original semantics


class NarrationState(TypedDict):
    model_client: object
    region_name: str
    crop_label: str
    warming_level_c: float
    climate_evidence: dict
    yield_change_pct: float
    literature: list[dict]
    narration: str | None
    verification: dict | None
    attempt: int
    status: str | None


def _generation_prompt(region_name: str, crop_label: str, warming_level_c: float, climate_evidence: dict, literature: list[dict]) -> str:
    literature_block = (
        "\n".join(f"- {p['text']} (source: {p['source']})" for p in literature)
        if literature
        else "(no literature retrieved)"
    )
    return (
        f"Explain the expected agricultural impact of {warming_level_c}°C of global warming on "
        f"{crop_label} in {region_name}, using only the climate evidence and literature below. "
        f"Do not state or imply a specific yield percentage — you have not been given one.\n\n"
        f"Climate evidence:\n"
        f"- Temperature change: {climate_evidence.get('temp_change_c')}°C\n"
        f"- Precipitation change: {climate_evidence.get('precip_change_pct')}%\n"
        f"- Extreme heat days change: {climate_evidence.get('extreme_heat_days')}\n"
        f"- Consecutive dry days change: {climate_evidence.get('consecutive_dry_days')}\n\n"
        f"Relevant literature:\n{literature_block}\n\n"
        f"Write 2-4 sentences, grounded only in the evidence and literature above."
    )


def _verification_prompt(narration_text: str, yield_change_pct: float) -> str:
    return (
        f"An independently computed crop model projects a yield change of {yield_change_pct}% "
        f"for this scenario. This projection was NOT shown to the model that wrote the narration "
        f"below — it was generated blind, from climate evidence and literature alone.\n\n"
        f"Narration:\n{narration_text}\n\n"
        f"Judge whether this narration is consistent with the {yield_change_pct}% projection: "
        f"does its implied direction and severity match, does it make any claim unsupported by "
        f"the evidence it was given, does it contradict the projection outright? Submit your "
        f"structured judgment via submit_verification."
    )


def _generate_node(state: NarrationState) -> dict:
    prompt = _generation_prompt(
        state["region_name"], state["crop_label"], state["warming_level_c"],
        state["climate_evidence"], state["literature"],
    )
    narration = state["model_client"].generate(prompt)
    return {"narration": narration, "attempt": state["attempt"] + 1}


def _verify_node(state: NarrationState) -> dict:
    verification = state["model_client"].verify(_verification_prompt(state["narration"], state["yield_change_pct"]))
    if verification["result"] == "PASS":
        status = "PASS"
    elif state["attempt"] >= MAX_RETRIES + 1:
        status = "SCIENTIFIC_DISAGREEMENT"
    else:
        status = "FAIL"  # route_after_verify sends this back to _generate_node
    return {"verification": verification, "status": status}


def _route_after_verify(state: NarrationState) -> str:
    return "generate" if state["status"] == "FAIL" else END


graph = StateGraph(NarrationState)
graph.add_node("generate", _generate_node)
graph.add_node("verify", _verify_node)
graph.set_entry_point("generate")
graph.add_edge("generate", "verify")
graph.add_conditional_edges("verify", _route_after_verify)

compiled_graph = graph.compile()


def run_narration_graph(
    model_client,
    region_name: str,
    crop_label: str,
    warming_level_c: float,
    climate_evidence: dict,
    yield_change_pct: float,
    literature: list[dict],
) -> NarrationState:
    """Runs the compiled graph once, start to finish (including its internal retries), and
    returns the final state. literature is resolved by the caller (narrate.py) before this runs —
    retrieval happens once, not per attempt, so it isn't part of the retry loop itself."""
    initial_state: NarrationState = {
        "model_client": model_client,
        "region_name": region_name,
        "crop_label": crop_label,
        "warming_level_c": warming_level_c,
        "climate_evidence": climate_evidence,
        "yield_change_pct": yield_change_pct,
        "literature": literature,
        "narration": None,
        "verification": None,
        "attempt": 0,
        "status": None,
    }
    return compiled_graph.invoke(initial_state)
