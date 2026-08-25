"""Swappable model-client interface for understanding() — see ADR-005: "The application should
interact with an abstraction such as 'understand this query.'... The implementation behind that
abstraction could initially be a fine-tuned model running on ordinary CPU infrastructure. It
could later be replaced by another model." The real fine-tuned model isn't trained yet (see
docs/overnight-2026-08-25.md) — this implements that same stable interface against Claude via
Bedrock's Converse API as the current concrete implementation, a real working system to build and
test the rest of the service against, not a placeholder. Swapping in the fine-tuned checkpoint
later is a drop-in replacement behind this same interface — that's the architecture's own stated
philosophy, not a compromise from it.
"""

from typing import Protocol

from langfuse import observe


class UnderstandingModelClient(Protocol):
    def resolve_tool_call(self, messages: list[dict], tools: list[dict], system_prompt: str) -> dict:
        """One turn of tool-calling: given the conversation so far and the available tools,
        returns the model's next message (may contain one or more tool-use blocks, or plain
        text if the model didn't call a tool)."""
        ...


class BedrockConverseUnderstandingClient:
    """Current concrete implementation. Model ID is a constructor argument, not hardcoded — this
    project's own environment has real access to several real models (verified live via
    bedrock:ListFoundationModels, not assumed); which one understanding() actually uses is a
    separate decision from the interface existing."""

    def __init__(self, bedrock_runtime_client, model_id: str):
        self._bedrock = bedrock_runtime_client
        self._model_id = model_id

    @observe(name="understanding:model_call", as_type="generation")
    def resolve_tool_call(self, messages: list[dict], tools: list[dict], system_prompt: str) -> dict:
        response = self._bedrock.converse(
            modelId=self._model_id,
            messages=messages,
            system=[{"text": system_prompt}],
            toolConfig={"tools": tools},
        )
        return response["output"]["message"]
