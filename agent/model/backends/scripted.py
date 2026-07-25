"""A backend that returns pre-set responses. No network, fully deterministic.

Two jobs, both real:

**Testing the validator.** Master plan §12 makes "feed deliberately malformed
model output, assert recovery" a Lane B gate. That test needs a model that emits
a specific broken response and then a specific good one, on demand — which no
real model can be made to do reliably.

**Demoing the loop without a GPU.** The macOS teammate at 10:00, and anyone
running the stack on a laptop with no model pulled, can still exercise the full
decision cycle end to end.

It is a legitimate `ModelBackend`, not a mock: the harness cannot tell it apart
from Ollama, so the code path under test is the real one.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

__all__ = ["ScriptedBackend"]


class ScriptedBackend:
    """Replays `responses` in order.

    Once exhausted it repeats the final response, so a retry loop configured for
    more attempts than the script provides degrades to "the model keeps making
    the same mistake" — the realistic behaviour — rather than raising an
    IndexError that would look like a harness bug.
    """

    name = "scripted"

    def __init__(self, responses: Iterable[str], *, model: str = "scripted") -> None:
        self._responses = list(responses)
        if not self._responses:
            raise ValueError("ScriptedBackend needs at least one response")
        self.model = model
        #: Every conversation it was asked to complete, for assertions about
        #: *what the retry loop actually fed back* — the interesting part.
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append([dict(m) for m in messages])
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]

    async def reachable(self) -> bool:
        return True
