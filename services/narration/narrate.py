"""The real ADR-007 flow: generate narration blind to the yield projection, verify it against
that held-out projection afterward, bounded retry, SCIENTIFIC_DISAGREEMENT as its own terminal
state rather than forcing false consistency.

Every non-PASS case is returned with enough structure to become the "structured evaluation data"
ADR-007 Step 5 calls for (query context, evidence, literature, generated text, verification
result) — capturing that to a real store (e.g. S3, keyed for later MLflow/eval-dataset use) is the
caller's job, not this module's; this module's job is only to produce a correct result per call.
"""

from langfuse import observe

MAX_RETRIES = 2


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


@observe(name="narration:narrate", as_type="chain")
def narrate(
    model_client,
    retrieve_fn,
    region_name: str,
    crop_label: str,
    warming_level_c: float,
    climate_evidence: dict,
    yield_change_pct: float,
) -> dict:
    """climate_evidence and literature go into generation; yield_change_pct never does — it's
    introduced only at the verification step (see module docstring). Returns:
    {"narration": str, "verification": {...}, "status": "PASS" | "SCIENTIFIC_DISAGREEMENT",
     "attempts": int, "literature": [...]}
    """
    literature = retrieve_fn(f"heat and water stress effects on {crop_label} yield")
    prompt = _generation_prompt(region_name, crop_label, warming_level_c, climate_evidence, literature)

    narration_text = None
    verification = None
    for attempt in range(1, MAX_RETRIES + 2):
        narration_text = model_client.generate(prompt)
        verification = model_client.verify(_verification_prompt(narration_text, yield_change_pct))

        if verification["result"] == "PASS":
            return {
                "narration": narration_text,
                "verification": verification,
                "status": "PASS",
                "attempts": attempt,
                "literature": literature,
            }

    return {
        "narration": narration_text,
        "verification": verification,
        "status": "SCIENTIFIC_DISAGREEMENT",
        "attempts": MAX_RETRIES + 1,
        "literature": literature,
    }
