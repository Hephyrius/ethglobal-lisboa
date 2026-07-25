"""vLLM, via its OpenAI-compatible server.

The scale-up path from Ollama: same request shape, but vLLM supports genuine
JSON-Schema-guided decoding, so the schema we already have can constrain the
sampler instead of merely being described in the prompt.

Guided decoding removes most layer-1 and layer-2 failures. It removes **none** of
layer 3 or 4 — a grammar can guarantee a well-formed `AllocationDecision` and
say nothing about whether the assets are permitted or the cited facts existed.
Validation runs identically on both backends.
"""

from __future__ import annotations

from typing import Any

from ..openai_compat import OpenAICompatClient

__all__ = ["VLLMBackend"]


def _guided_json_hint(json_schema: dict[str, Any] | None) -> dict[str, Any]:
    if not json_schema:
        return {"response_format": {"type": "json_object"}}
    return {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "allocation_decision",
                "schema": json_schema,
                "strict": True,
            },
        }
    }


class VLLMBackend:
    """`ModelBackend` over a vLLM OpenAI-compatible server."""

    name = "vllm"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self._client = OpenAICompatClient(
            base_url=base_url,
            model=model,
            timeout=timeout,
            api_key=api_key,
            structured_output=_guided_json_hint,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        return await self._client.complete(
            messages, json_schema=json_schema, temperature=temperature
        )

    async def reachable(self) -> bool:
        return await self._client.reachable()

    async def has_model(self) -> bool | None:
        return await self._client.has_model()
