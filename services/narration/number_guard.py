"""Deterministic number-provenance guard — the regex half of the narration verification gate's
extension named in docs/adr/adr-007-narration-verification-gate.md's Update: the LLM verifier
judges direction/severity, but nothing previously checked whether a specific number in the
narration text actually traces back to something generation was given. Ordinary code, not a
model: extract every numeric token from the generated narration, extract every numeric token
available to generation (the warming level, climate evidence values, retrieved literature text),
and flag any narration number absent from that combined set. Runs before the LLM verify call, not
instead of it (see graph.py) — this closes the fabricated-number hallucination vector
specifically; it does not judge whether a real, correctly-sourced number is used to support the
right claim — that's still the LLM verifier's job (direction/severity) and the covariation
check's (mechanism plausibility).
"""

import re

from langfuse import observe

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# A narration number is allowed to round relative to its source — e.g. "20%" narrating a real
# 20.34, or "2 degrees" narrating a 2.0°C warming level — not required to reproduce the source's
# own precision. Deliberately generous for whole-number narration, while still catching a figure
# with no real source anywhere near it.
_TOLERANCE = 0.5

# Matching is on magnitude, not signed value: narration routinely states a magnitude with a
# direction word instead of a sign ("precipitation falls by 12%" for a stored -12.0), so requiring
# the sign to match too would false-flag ordinary phrasing, not catch a real fabrication.


def _numbers_in(text: str) -> list[float]:
    return [float(match) for match in _NUMBER_RE.findall(text)]


def _source_numbers(climate_evidence: dict, literature: list[dict], warming_level_c: float) -> list[float]:
    numbers = [warming_level_c]
    numbers.extend(value for value in climate_evidence.values() if isinstance(value, int | float))
    for entry in literature:
        numbers.extend(_numbers_in(entry.get("text", "")))
    return numbers


@observe(name="narration:number_guard", as_type="tool")
def check_number_provenance(narration: str, climate_evidence: dict, literature: list[dict], warming_level_c: float) -> dict:
    """Returns {"passed": bool, "unsupported_numbers": [float, ...]} — every number in `narration`
    not within _TOLERANCE of some number in climate_evidence, the retrieved literature, or the
    warming level itself."""
    source_numbers = _source_numbers(climate_evidence, literature, warming_level_c)
    unsupported = [
        number
        for number in _numbers_in(narration)
        if not any(abs(abs(number) - abs(source)) <= _TOLERANCE for source in source_numbers)
    ]
    return {"passed": not unsupported, "unsupported_numbers": unsupported}
