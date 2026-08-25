"""Real, hand-curated eval set for understanding() — not LLM-generated, so every expected answer
is something a human actually decided, and the set stays small enough to review by eye.

Two jobs, same set: (1) measure the current baseline (Claude Haiku via Bedrock) for real, before
deciding whether/how to fine-tune anything — see run_baseline_eval.py; (2) the traces from
questions the baseline gets right double as real (not fabricated) synthetic training data for the
eventual fine-tune, following standard teacher-distillation practice of only training on the
teacher's correct outputs.

Canonical region coordinates match frontend/src/api/questionParsing.ts's KNOWN_REGIONS exactly —
reusing this project's one existing set of real, already-validated region ground truth rather than
inventing a second one.
"""

_REGIONS = {
    "occitanie": (2.15, 43.6),
    "iowa": (-93.6, 42.0),
    "punjab": (75.3, 31.1),
    "nile delta": (31.0, 30.8),
    "mekong delta": (105.8, 10.0),
}

# Loose tolerance: geocode() returns Esri's real candidates, not exact KNOWN_REGIONS coordinates
# (a real place has some geometric extent) — this checks the model picked a candidate actually
# near the right place, not byte-exact agreement with a hand-picked reference point.
REGION_TOLERANCE_DEGREES = 2.0


def _resolved(question: str, region: str, crop: str, warming_level_c: float) -> dict:
    lon, lat = _REGIONS[region]
    return {
        "question": question,
        "expected_kind": "resolved",
        "expected_crop": crop,
        "expected_region_lon": lon,
        "expected_region_lat": lat,
        "expected_warming_level_c": warming_level_c,
    }


def _clarify(question: str, reason: str) -> dict:
    return {"question": question, "expected_kind": "clarify", "reason": reason}


EVAL_QUESTIONS = [
    # Happy path — one per crop, varied phrasing, varied warming levels.
    _resolved("How will maize yields in Iowa change at 2°C of warming?", "iowa", "maize", 2.0),
    _resolved("What happens to corn production in Iowa if we hit 3 degrees of warming?", "iowa", "maize", 3.0),
    _resolved("Spring wheat yields in Occitanie at 1.5C of warming?", "occitanie", "spring_wheat", 1.5),
    _resolved("How does 2 degrees of global warming affect wheat in Occitanie?", "occitanie", "spring_wheat", 2.0),
    _resolved("Soybean yield change in Iowa at 2.5°C warming", "iowa", "soy", 2.5),
    _resolved("What will happen to soy in Iowa when it's 4 degrees warmer?", "iowa", "soy", 4.0),
    _resolved("Rice yields in the Mekong Delta at 2°C of warming", "mekong delta", "rice", 2.0),
    _resolved("How will rice production in the Mekong Delta change at 3 degrees warming?", "mekong delta", "rice", 3.0),
    _resolved("Wheat yields in Punjab at 2°C global warming", "punjab", "spring_wheat", 2.0),
    _resolved("Maize in the Nile Delta at 1.5 degrees of warming", "nile delta", "maize", 1.5),
    _resolved("Rice yields in Punjab at 2.5C warming", "punjab", "rice", 2.5),
    _resolved("How will soybeans in the Nile Delta fare at 3°C warming?", "nile delta", "soy", 3.0),
    # Missing crop — should clarify, not guess one.
    _clarify("How will yields in Iowa change at 2°C of warming?", "no crop named"),
    _clarify("What happens to crop production in Punjab at 3 degrees of warming?", "no specific crop named"),
    _clarify("How does global warming affect farming in Occitanie?", "no crop, no warming level"),
    _clarify("What will happen in the Mekong Delta at 2°C warming?", "no crop named"),
    # Missing warming level — should clarify, not assume one.
    _clarify("How will maize yields in Iowa change?", "no warming level stated"),
    _clarify("What happens to rice production in the Mekong Delta as the climate warms?", "no specific warming level"),
    _clarify("Soybean yields in Iowa under climate change?", "no warming level stated"),
    _clarify("Wheat yields in Punjab in a warmer future?", "no warming level stated"),
    # Ambiguous region — Esri's own top-ranked candidate is documented to be wrong here (see
    # orchestrator.py's SYSTEM_PROMPT docstring) — a model that just takes the top result fails
    # this one; a model that judges candidates should still resolve it correctly.
    _resolved("How will rice yields in the Mekong Delta change at 2°C of warming?", "mekong delta", "rice", 2.0),
    _clarify("How will crops fare in the Delta region at 2°C warming?", "region too vague to be one place"),
    # Unsupported crop — the system prompt explicitly designs this as a clarify case (crop is not
    # one of the four supported ones), not a silent wrong resolution and not a hard refusal.
    _clarify("How will barley yields in Iowa change at 2°C of warming?", "unsupported crop"),
    _clarify("What happens to cotton production in Punjab at 3 degrees of warming?", "unsupported crop"),
    _clarify("How will potato yields in Occitanie change at 2°C warming?", "unsupported crop"),
]
