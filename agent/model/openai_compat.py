"""One OpenAI-compatible chat-completions client, shared by every backend.

Standardizing on this request shape is a locked decision
(`plans/initiate_plan.md` §3.1): Ollama and vLLM both expose it, so they work
behind a single interface today and a hosted provider is a drop-in later without
the decision loop noticing.

What actually differs between backends is one thing — how you ask for structured
output. Ollama takes `response_format: {"type": "json_object"}`; vLLM accepts a
full JSON-Schema-guided decode. That difference is a single hook here, which is
why `backends/ollama.py` and `backends/vllm.py` are a dozen lines each rather
than two copies of an HTTP client.

**The hint is never a guarantee.** `curator_schema.ports.ModelBackend` says so
explicitly, and it is true in practice: `json_object` mode constrains syntax, not
shape, and guided decoding still lets a model emit a well-formed decision that
breaks the mandate. Everything from here goes through
`agent/model/validation.py`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx

__all__ = ["OpenAICompatClient", "ModelUnavailable", "model_is_served"]


def model_is_served(wanted: str, served: list[str]) -> bool:
    """Whether `wanted` is among `served`.

    **Ollama tags are exact.** Verified against a live server holding only
    `qwen2.5:3b-instruct-q4_K_M`: `/api/show` answers 200 for that exact tag and
    **404 for `qwen2.5:3b`, `qwen2.5`, and `qwen2.5:14b-instruct`**. An earlier
    version of this matched on the base name before the colon, which reported a
    server with the 3B pulled as ready to serve the 14B — the precise false
    green this check exists to prevent.

    The one allowance is Ollama's own default-tag rule: a bare name means
    `:latest`. Everything else must match exactly.
    """
    if wanted in served:
        return True
    if ":" not in wanted:
        return f"{wanted}:latest" in served
    return False

log = logging.getLogger(__name__)

#: A hint builder maps the requested JSON Schema to extra request-body fields.
StructuredOutputHint = Callable[[dict[str, Any] | None], dict[str, Any]]


class ModelUnavailable(RuntimeError):
    """The model endpoint could not be reached or returned an unusable response.

    Distinct from a validation failure: the model said nothing, rather than
    saying something wrong. The cycle records this as `failed`, not `rejected` —
    conflating "the server is down" with "the model is unreliable" would make
    the decision feed lie about why a tick produced nothing.
    """


class OpenAICompatClient:
    """Transport for any `/chat/completions` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        api_key: str | None = None,
        structured_output: StructuredOutputHint | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._api_key = api_key
        self._structured_output = structured_output

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if self._structured_output:
            payload.update(self._structured_output(json_schema))

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            raise ModelUnavailable(
                f"{self._base_url} returned {exc.response.status_code}: "
                f"{exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"could not reach {self._base_url}: {exc}") from exc

        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelUnavailable(
                f"unexpected response shape from {self._base_url}: {str(body)[:300]}"
            ) from exc

    async def models(self) -> list[str] | None:
        """Model ids this endpoint serves, or None if it could not be asked.

        Uses the listing rather than a test completion: it is instant, and a
        loaded-but-slow model should read as healthy rather than timing out a
        health check.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/models", headers=self._headers())
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        return [entry.get("id", "") for entry in body.get("data") or []]

    async def reachable(self) -> bool:
        """Whether the endpoint answers at all."""
        return await self.models() is not None

    async def has_model(self) -> bool | None:
        """Whether the **configured** model is actually served. None if unreachable.

        A running server is not a working one. `ollama serve` answers happily
        with nothing pulled, so a health check that only pings the endpoint
        reports green right up until the first tick fails with
        `model 'qwen2.5:3b' not found`. Distinguishing the two is the difference
        between a one-line fix and debugging the harness during a demo.

        Ollama reports models with their tag (`qwen2.5:3b-instruct-q4_K_M`) but
        answers to the bare name too, so a prefix match on the colon avoids a
        false negative from a tag suffix.
        """
        served = await self.models()
        if served is None:
            return None
        return model_is_served(self._model, served)
