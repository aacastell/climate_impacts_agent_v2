"""Model clients for narration generation and verification — both via Bedrock Converse, same
"swappable behind a stable interface" pattern as services/understanding/model_client.py. Bedrock
is the real candidate per ADR-007's own accompanying decision: "Bedrock is the candidate for
narration specifically because it needs more capability than the agent's own tool-calling model."
"""

import json
from typing import Protocol

from langfuse import observe


class NarrationModelClient(Protocol):
    def generate(self, prompt: str) -> str: ...
    def verify(self, prompt: str) -> dict: ...


_VERIFICATION_TOOL = [
    {
        "toolSpec": {
            "name": "submit_verification",
            "description": "Submit the structured consistency judgment.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "result": {"type": "string", "enum": ["PASS", "FAIL"]},
                        "direction_match": {"type": "boolean"},
                        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
                        "contradictions": {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number"},
                        "notes": {"type": "string"},
                        "mechanism_consistent": {
                            "type": "boolean",
                            "description": (
                                "Only judge this when the prompt provides a top-covariation driver. "
                                "False if the narration attributes the impact to a clearly different, "
                                "unrelated mechanism than that driver. Omit entirely if the prompt "
                                "gives no driver to check against."
                            ),
                        },
                    },
                    "required": ["result", "direction_match", "unsupported_claims", "contradictions", "confidence"],
                }
            },
        }
    }
]


class BedrockConverseNarrationClient:
    def __init__(self, bedrock_runtime_client, model_id: str):
        self._bedrock = bedrock_runtime_client
        self._model_id = model_id

    @observe(name="narration:generate", as_type="generation")
    def generate(self, prompt: str) -> str:
        response = self._bedrock.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
        )
        text_blocks = [b["text"] for b in response["output"]["message"]["content"] if "text" in b]
        return "".join(text_blocks)

    @observe(name="narration:verify", as_type="evaluator")
    def verify(self, prompt: str) -> dict:
        response = self._bedrock.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            toolConfig={"tools": _VERIFICATION_TOOL, "toolChoice": {"tool": {"name": "submit_verification"}}},
        )
        for block in response["output"]["message"]["content"]:
            if "toolUse" in block and block["toolUse"]["name"] == "submit_verification":
                return block["toolUse"]["input"]
        raise ValueError("Model did not call submit_verification — cannot extract a structured judgment")
