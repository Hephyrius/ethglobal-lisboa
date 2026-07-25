"""xAI (Grok), via its OpenAI-compatible endpoint at `https://api.x.ai/v1`.

The default backend when `XAI_API_KEY` is set, falling back to Ollama when it is
not. That reverses `plans/initiate_plan.md` §2's local-first default, on the
operator's instruction and for a measured reason: the local 3B **cannot size a
trade in the right direction under correction.** Two reproducible three-attempt
exhaustions on the demo vault, identical both times — wrong direction, the same
wrong direction after being told explicitly to swap, then a 100% liquidation
into a single asset that three constraint layers had to catch. A curator that
only ever gets rejected is not a curator.

**Model: `grok-4.20-0309-non-reasoning`, the cheapest per decision — which is
not the cheapest per token.** Both halves were measured rather than assumed.

The model list and its prices came from `GET /v1/language-models`, not the docs:
they disagreed, and every third-party blog still advertises a cheaper "fast"
tier this account cannot see. That named `grok-build-0.1` as the per-token floor
at $1.00/M in, $2.00/M out.

Running one real curator prompt through each, billed by xAI's own
`cost_in_usd_ticks`, says otherwise:

    model                         $/decision   latency   reasoning   facts cited
    grok-build-0.1                   $0.0216     60.8s      10,195             1
    grok-4.20-0309-non-reasoning     $0.0015      2.3s           0           5-6
    grok-4.3 (reasoning_effort low)  $0.0027      9.2s         707             0

`grok-build-0.1` is a **reasoning** model and bills its reasoning as output. It
spent 10,195 tokens thinking in order to emit 267, so the nominally cheapest
option costs **14x more per decision**. It is also 26x slower, which settles it
independently of price: a 60-second tick cannot be demoed. Turning the reasoning
down is not available — it rejects `reasoning_effort` with
*"Model grok-build-0.1 does not support parameter reasoning_effort"*, so that
door is closed rather than merely untried.

The chosen model is therefore the cheapest, the fastest **and** the one citing
the most facts — no tradeoff was taken. At $0.0015 a decision, a thousand ticks
costs $1.50; three retries on every one of them costs $4.50.

`$0.0015` is the steady-state figure and the honest one to quote: the first call
on a cold cache was $0.0034, after which **2,112 of 2,133 prompt tokens hit
cache** at a fifth of the input rate. Caching needs no configuration, but it
does mean the system prompt should stay stable — churning it re-prices every
tick at the uncached rate.

**Structured output is genuine JSON-Schema-guided decoding**, verified live
against `grok-build-0.1` rather than assumed from the OpenAI-compatibility
claim: a `strict: true` `json_schema` request returns a conforming object. That
puts this backend in vLLM's class rather than Ollama's, so most layer-1 and
layer-2 failures disappear. It removes **none** of layers 3-6 — a grammar can
guarantee a well-formed `AllocationDecision` and says nothing about whether the
assets are permitted, the venue is granted, or the trade closes the gap it
claims to. Validation runs identically on every backend.

One caveat worth knowing: `grok-build-0.1` is a reasoning model and bills its
reasoning as output tokens, so a tick costs more than the visible answer
suggests. It is still fractions of a cent — see `agent/README.md`.
"""

from __future__ import annotations

from typing import Any

from ..openai_compat import OpenAICompatClient

__all__ = ["GrokBackend"]


def _guided_json_hint(json_schema: dict[str, Any] | None) -> dict[str, Any]:
    """Ask for schema-guided decoding when we have a schema, JSON syntax otherwise.

    Deliberately a copy of vLLM's hint rather than a shared helper: the whole
    point of one-file-per-backend is that a provider changing its structured
    output contract touches exactly one file. Fourteen duplicated lines are
    cheaper than a coupling that makes two backends fail together.
    """
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


class GrokBackend:
    """`ModelBackend` over xAI's hosted API."""

    name = "grok"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout: float = 120.0,
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
        """Whether xAI serves the configured model. None if it is not answering.

        Worth keeping for a hosted provider even though nothing has to be
        pulled: a retired model id, or a key whose account cannot see a given
        tier, both present as a 404 on the first tick and as green on any check
        that merely pings the endpoint.
        """
        return await self._client.has_model()
