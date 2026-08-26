"""The real ADR-007 flow: generate narration blind to the yield projection, verify it against
that held-out projection afterward, bounded retry, SCIENTIFIC_DISAGREEMENT as its own terminal
state rather than forcing false consistency. The actual generate/verify/retry control flow now
lives in graph.py as a real LangGraph graph (see ADR-009) — this module resolves retrieval once
up front, hands off to the graph, and reshapes its output into this service's stable public
result contract so callers (app.py, tests) never depend on the graph's internal state shape.

Every non-PASS case is returned with enough structure to become the "structured evaluation data"
ADR-007 Step 5 calls for (query context, evidence, literature, generated text, verification
result) — capturing that to a real store (e.g. S3, keyed for later MLflow/eval-dataset use) is the
caller's job, not this module's; this module's job is only to produce a correct result per call.
"""

from langfuse import observe

from graph import run_narration_graph

MAX_RETRIES = 2


@observe(name="narration:narrate", as_type="chain")
def narrate(
    model_client,
    retrieve_fn,
    region_name: str,
    crop_label: str,
    warming_level_c: float,
    climate_evidence: dict,
    yield_change_pct: float,
    driver_covariation: dict,
) -> dict:
    """climate_evidence and literature go into generation; yield_change_pct and
    driver_covariation never do — both are introduced only at the verification step (see module
    docstring). Pass {} when the caller has no region-cell data for this query (e.g. a region too
    small to have computed anything) — covariation_check's own "nothing confident enough to
    check" path handles that explicitly, so this is a real input, not an optional convenience.
    Returns: {"narration": str, "verification": {...}, "status": "PASS" | "SCIENTIFIC_DISAGREEMENT",
     "attempts": int, "literature": [...], "number_guard": {...}, "covariation_result": {...}}
    """
    literature = retrieve_fn(f"heat and water stress effects on {crop_label} yield")

    final_state = run_narration_graph(
        model_client, region_name, crop_label, warming_level_c, climate_evidence, yield_change_pct,
        literature, driver_covariation,
    )

    return {
        "narration": final_state["narration"],
        "verification": final_state["verification"],
        "status": final_state["status"],
        "attempts": final_state["attempt"],
        "literature": literature,
        "number_guard": final_state["number_guard"],
        "covariation_result": final_state["covariation_result"],
    }
