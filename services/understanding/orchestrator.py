"""The real interpret() orchestration loop — resolves a free-text question to a structured
(region, crop, warming_level, year) tuple via real tool-calling (ADR-005). The model decides which
tools to call, in what order, and how to recover from ambiguity; the tools themselves
(geocode/crop/timecode) are the already-real, already-tested deterministic functions in
climate_pipeline.agent.tools — this loop adds orchestration only, no new scientific logic.

geocode() deliberately returns multiple unranked candidates (see that module's docstring — Esri's
own top-ranked result for "Mekong Delta" is wrong two times out of three). Picking among them is
exactly the ambiguity-diagnosis ADR-005 Step 4 calls genuinely agentic, so the system prompt
explicitly tells the model it must judge, not just take the first result — and to call `clarify`
rather than guess when candidates are genuinely tied.
"""

from langfuse import observe

from climate_pipeline.agent.tools import crop as crop_tool
from climate_pipeline.agent.tools import geocode as geocode_tool
from climate_pipeline.agent.tools import timecode as timecode_tool

SYSTEM_PROMPT = (
    "You resolve a user's climate-impact question to a structured (region, crop, warming level, "
    "year) tuple by calling the geocode, crop, and timecode tools, in whatever order makes sense. "
    "geocode() returns multiple candidate places with metadata (label, categories, "
    "supplemental_categories, relevance) for a named region — it does not pick one for you, and "
    "its own top-ranked candidate is frequently wrong. You must judge which candidate is actually "
    "correct given the question's context (an agricultural/climate question about a place is "
    "unlikely to mean a same-named restaurant or business). "
    "If no supported crop is named (maize, spring_wheat, soy, rice — including synonyms like corn "
    "or wheat), or no warming level is stated, or the region is genuinely ambiguous between "
    "multiple similarly plausible candidates, call `clarify` with a specific question rather than "
    "guessing. Once region, crop, and warming level (converted to a year via timecode) are all "
    "confidently resolved, call `resolved` with the final structured answer — never state a "
    "resolution in plain text, always call `resolved`."
)

TOOLS = [
    {
        "toolSpec": {
            "name": "geocode",
            "description": (
                "Resolve free text naming a geographic region to real candidate places via Amazon "
                "Location Service. Returns a list of candidates, unranked by correctness — you "
                "must judge which one is right."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "region_text": {"type": "string", "description": "The region name as it appears in the question"}
                    },
                    "required": ["region_text"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "crop",
            "description": "Resolve free text to one of the four supported crops (maize, spring_wheat, soy, rice), or null if none is named/supported.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"question": {"type": "string"}},
                    "required": ["question"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "timecode",
            "description": "Resolve a stated global warming level in Celsius to the year whose 20-year window best matches it.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"warming_level_c": {"type": "number"}},
                    "required": ["warming_level_c"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "clarify",
            "description": "Call this instead of guessing when the question is genuinely ambiguous or missing required information.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"question": {"type": "string", "description": "The clarifying question to ask the user"}},
                    "required": ["question"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "resolved",
            "description": "Call this once region, crop, and warming level are all confidently resolved.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "region_name": {"type": "string"},
                        "region_lon": {"type": "number"},
                        "region_lat": {"type": "number"},
                        "crop": {"type": "string"},
                        "warming_level_c": {"type": "number"},
                        "year": {"type": "integer"},
                    },
                    "required": ["region_name", "region_lon", "region_lat", "crop", "warming_level_c", "year"],
                }
            },
        }
    },
]

MAX_TURNS = 6


@observe(name="tool:geocode", as_type="tool")
def _call_geocode(location_client, location_index_name: str, region_text: str):
    return geocode_tool(location_client, location_index_name, region_text)


@observe(name="tool:crop", as_type="tool")
def _call_crop(question: str):
    return crop_tool(question)


@observe(name="tool:timecode", as_type="tool")
def _call_timecode(gwl_year_table: list[dict], warming_level_c: float):
    return timecode_tool(gwl_year_table, warming_level_c)


def _run_tool(name: str, tool_input: dict, location_client, location_index_name: str, gwl_year_table: list[dict]) -> dict:
    """Always returns a JSON *object* (dict), never a bare list/string/int/None — a real,
    confirmed-live Bedrock Converse requirement: toolResult.content[].json must be an object.
    geocode() returns a list, crop() a string-or-None, timecode() an int — none of those are
    valid on their own; each gets wrapped under a named key instead.
    """
    # Traced per-tool (Langfuse as_type="tool"), not just as one opaque "ran a tool" span — see
    # ADR-005's stated trace shape: "query -> agent decisions -> tool calls -> ...".
    if name == "geocode":
        return {"candidates": _call_geocode(location_client, location_index_name, tool_input["region_text"])}
    if name == "crop":
        return {"crop": _call_crop(tool_input["question"])}
    if name == "timecode":
        return {"year": _call_timecode(gwl_year_table, tool_input["warming_level_c"])}
    return {"error": f"unknown tool {name!r}"}


@observe(name="understanding:interpret", as_type="agent")
def interpret(
    model_client,
    location_client,
    location_index_name: str,
    gwl_year_table: list[dict],
    question: str,
    *,
    trace: list | None = None,
) -> dict:
    """Runs the real tool-calling loop. Returns one of:
    {"kind": "resolved", "region": {...}, "crop": ..., "warmingLevelC": ..., "year": ...}
    {"kind": "clarify", "question": ..., "tool_use_id": ...}
    {"kind": "refusal", "reason": "no_resolution", "message": ...}

    trace: two jobs. If given empty (or None), the exact real message list (question, tool
    calls, tool results, final turn) is built into it in place — the hook fine-tuning data
    generation needs, so training examples come from this real loop rather than a second,
    drift-prone copy of it. If given non-empty, this call *resumes* a prior conversation instead
    of starting one — `question` is then ignored, since the original question is already the
    first entry in `trace`. Resuming a clarify() round-trip means the caller must have already
    appended the user's answer as a toolResult for the pending clarify call's tool_use_id (see
    ADR-005's Accompanying decisions — the query_id/short-lived-store design this supports) —
    Bedrock's Converse API requires every toolUse to be paired with a toolResult in the very next
    turn before the conversation can continue at all; a plain follow-up message wouldn't be a
    valid resume.
    """
    messages = trace if trace is not None else []
    if not messages:
        messages.append({"role": "user", "content": [{"text": question}]})

    for _ in range(MAX_TURNS):
        output_message = model_client.resolve_tool_call(messages, TOOLS, SYSTEM_PROMPT)
        messages.append(output_message)

        tool_use_blocks = [block["toolUse"] for block in output_message["content"] if "toolUse" in block]
        if not tool_use_blocks:
            break  # plain text, no tool call — model didn't reach a resolution

        tool_results = []
        for tool_use in tool_use_blocks:
            name = tool_use["name"]
            tool_input = tool_use["input"]

            if name == "clarify":
                return {"kind": "clarify", "question": tool_input["question"], "tool_use_id": tool_use["toolUseId"]}

            if name == "resolved":
                return {
                    "kind": "resolved",
                    "region": {
                        "name": tool_input["region_name"],
                        "lon": tool_input["region_lon"],
                        "lat": tool_input["region_lat"],
                    },
                    "crop": tool_input["crop"],
                    "warmingLevelC": tool_input["warming_level_c"],
                    "year": tool_input["year"],
                }

            result = _run_tool(name, tool_input, location_client, location_index_name, gwl_year_table)
            tool_results.append(
                {"toolResult": {"toolUseId": tool_use["toolUseId"], "content": [{"json": result}]}}
            )

        messages.append({"role": "user", "content": tool_results})

    return {
        "kind": "refusal",
        "reason": "no_resolution",
        "message": "Could not resolve the question within the allotted tool-calling turns.",
    }
