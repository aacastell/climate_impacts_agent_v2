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

Real extension, not the original three-node design: two deterministic checks now run between
generate and verify — guard_numbers (does every number in the narration trace back to something
generation was given — see number_guard.py) and covariation_check (which climate driver's spatial
pattern best co-varies with yield in this region — see
pipeline/climate_pipeline/process/covariation.py). Both close a real, previously-named gap: the
LLM verifier judged direction/severity, but nothing checked number provenance or gave it a signal
to judge narrated mechanism claims against. guard_numbers can independently fail and retry (a
fabricated number is unambiguous, no model judgment needed); covariation_check never fails on its
own — matching a driver name to a narration's free-text mechanism claim is a semantic judgment,
so it only enriches state for verify to judge (mechanism_consistent), it doesn't gate by itself.

State intentionally carries model_client/retrieve_fn as plain objects, not serialized handles —
this graph is compiled and run in-process per request, never checkpointed or persisted across a
process boundary, so there's no requirement that state be JSON-serializable.
"""

from typing import TypedDict

from langgraph.graph import END, StateGraph
from langfuse import observe

from number_guard import check_number_provenance

MAX_RETRIES = 2  # total attempts = MAX_RETRIES + 1, matching narrate.py's original semantics


class NarrationState(TypedDict):
    model_client: object
    region_name: str
    crop_label: str
    warming_level_c: float
    climate_evidence: dict
    yield_change_pct: float
    literature: list[dict]
    driver_covariation: dict
    narration: str | None
    number_guard: dict | None
    covariation_result: dict | None
    verification: dict | None
    attempt: int
    status: str | None


def _attempts_exhausted(state: NarrationState) -> bool:
    return state["attempt"] >= MAX_RETRIES + 1


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


def _verification_prompt(narration_text: str, yield_change_pct: float, covariation_result: dict | None) -> str:
    mechanism_note = ""
    if covariation_result and covariation_result.get("checked"):
        mechanism_note = (
            f"\n\nSeparately, a deterministic statistical check (not visible to whoever wrote the "
            f"narration) found that, within this region, {covariation_result['top_driver']} has the "
            f"strongest spatial correlation with the yield outcome (Spearman r="
            f"{covariation_result['top_r']:.2f}). This is a correlational signal, not proof of "
            f"causation — but if the narration attributes the impact to a clearly different, "
            f"unrelated mechanism, set mechanism_consistent=false. Omit mechanism_consistent "
            f"entirely if the narration's claimed mechanism is plausibly related to this driver."
        )
    return (
        f"An independently computed crop model projects a yield change of {yield_change_pct}% "
        f"for this scenario. This projection was NOT shown to the model that wrote the narration "
        f"below — it was generated blind, from climate evidence and literature alone."
        f"{mechanism_note}\n\n"
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


def _guard_numbers_node(state: NarrationState) -> dict:
    result = check_number_provenance(state["narration"], state["climate_evidence"], state["literature"], state["warming_level_c"])
    update: dict = {"number_guard": result}
    if not result["passed"] and _attempts_exhausted(state):
        update["status"] = "SCIENTIFIC_DISAGREEMENT"
    return update


def _route_after_guard_numbers(state: NarrationState) -> str:
    if state["number_guard"]["passed"]:
        return "covariation_check"
    return END if state["status"] == "SCIENTIFIC_DISAGREEMENT" else "generate"


@observe(name="narration:covariation_check", as_type="tool")
def _select_top_driver(driver_covariation: dict) -> dict:
    """Deterministic ranking, not judgment: which driver has the strongest |r| among drivers with
    enough region cells to trust (see covariation.py's MIN_CELLS_FOR_CONFIDENCE). Whether the
    narration's claimed mechanism actually matches that driver is a semantic call the LLM verifier
    makes (mechanism_consistent), not this function — matching a driver name to free-text prose
    isn't something regex or a correlation coefficient can safely decide on its own."""
    confident = {
        name: info for name, info in driver_covariation.items()
        if info.get("r") is not None and not info.get("low_confidence")
    }
    if not confident:
        return {"checked": False, "top_driver": None, "top_r": None}
    top_driver = max(confident, key=lambda name: abs(confident[name]["r"]))
    return {"checked": True, "top_driver": top_driver, "top_r": confident[top_driver]["r"]}


def _covariation_check_node(state: NarrationState) -> dict:
    return {"covariation_result": _select_top_driver(state["driver_covariation"])}


def _verify_node(state: NarrationState) -> dict:
    verification = state["model_client"].verify(
        _verification_prompt(state["narration"], state["yield_change_pct"], state["covariation_result"])
    )
    mechanism_flagged = verification.get("mechanism_consistent") is False
    if verification["result"] == "PASS" and not mechanism_flagged:
        status = "PASS"
    elif _attempts_exhausted(state):
        status = "SCIENTIFIC_DISAGREEMENT"
    else:
        status = "FAIL"  # route_after_verify sends this back to _generate_node
    return {"verification": verification, "status": status}


def _route_after_verify(state: NarrationState) -> str:
    return "generate" if state["status"] == "FAIL" else END


graph = StateGraph(NarrationState)
graph.add_node("generate", _generate_node)
graph.add_node("guard_numbers", _guard_numbers_node)
graph.add_node("covariation_check", _covariation_check_node)
graph.add_node("verify", _verify_node)
graph.set_entry_point("generate")
graph.add_edge("generate", "guard_numbers")
graph.add_conditional_edges("guard_numbers", _route_after_guard_numbers)
graph.add_edge("covariation_check", "verify")
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
    driver_covariation: dict,
) -> NarrationState:
    """Runs the compiled graph once, start to finish (including its internal retries), and
    returns the final state. literature and driver_covariation are both resolved by the caller
    (narrate.py / narrate_handler.py) before this runs — retrieval and the grid-correlation
    computation each happen once, not per attempt, so neither is part of the retry loop itself."""
    initial_state: NarrationState = {
        "model_client": model_client,
        "region_name": region_name,
        "crop_label": crop_label,
        "warming_level_c": warming_level_c,
        "climate_evidence": climate_evidence,
        "yield_change_pct": yield_change_pct,
        "literature": literature,
        "driver_covariation": driver_covariation,
        "narration": None,
        "number_guard": None,
        "covariation_result": None,
        "verification": None,
        "attempt": 0,
        "status": None,
    }
    return compiled_graph.invoke(initial_state)
