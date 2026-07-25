"""Ollama, via its OpenAI-compatible endpoint.

The local-first default (`plans/initiate_plan.md` §2 — no model API key, no
hosted dependency at the demo).

Ollama's OpenAI-compatible surface supports `response_format: {"type":
"json_object"}`, which constrains the model to emit syntactically valid JSON.
It does **not** constrain the *shape*, so the schema still has to be described in
the prompt and the output still has to be validated. That is exactly why
`agent/model/validation.py` exists and why layer 2 catches as much as it does.
"""

from __future__ import annotations

from typing import Any

from ..openai_compat import OpenAICompatClient

__all__ = ["OllamaBackend"]


def _json_object_hint(_: dict[str, Any] | None) -> dict[str, Any]:
    # The schema argument is ignored deliberately: Ollama's OpenAI-compatible
    # endpoint has no guided-decode parameter, so passing one would be silently
    # dropped and give a false sense of enforcement.
    return {"response_format": {"type": "json_object"}}


class OllamaBackend:
    """`ModelBackend` over a local Ollama server."""

    name = "ollama"

    def __init__(self, *, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.model = model
        self._client = OpenAICompatClient(
            base_url=base_url,
            model=model,
            timeout=timeout,
            structured_output=_json_object_hint,
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
