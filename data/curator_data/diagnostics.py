"""Turning failures into observations an agent can act on.

The reader of a `SourceError` is a language model deciding whether to move
capital. `ConnectionError: [Errno 11001] getaddrinfo failed` is a stack trace
wearing a sentence: it says nothing about whether the market behind it is
risky, unreachable, or simply not indexed here.

So every failure this lane reports is translated once, here, into plain
language plus the consequence the agent should draw. Two rules learned the
expensive way:

  * **Keep the number.** "slow" is an opinion; "no response within 6s" is a
    fact the agent can weigh against the freshness of everything else.
  * **Say what already happened.** "skipped so it does not delay the other
    protocols" tells the model the rest of the snapshot is intact. Without it,
    one dead protocol reads like a dead data layer — which is exactly how 35
    of 36 journalled ticks opened before Wave 1 split the channels.

`CONSEQUENCE` constants exist so the same situation is never explained two
different ways in two sources.
"""

from __future__ import annotations

import asyncio

import httpx

# ── consequences, so the same situation reads the same everywhere ─────────

SKIPPED_TO_PROTECT_LATENCY = (
    "skipped so it does not delay the other protocols; the rest of this snapshot is unaffected"
)
TREAT_AS_STALE = "the agent should treat it as stale"
OTHERS_UNAFFECTED = "the other facts in this snapshot are unaffected"
RETRY_NEXT_TICK = "it should be reachable again next tick; this snapshot is missing it"
NEEDS_OPERATOR = "no retry will fix this - an operator must set the credential"
DROPPED_NOT_SHOWN = "dropped rather than shown, because a wrong number is worse than a missing one"


def explain_exception(exc: BaseException) -> str:
    """A plain-language observation for a failure, keeping any status code.

    Deliberately falls back to the exception type and message rather than
    something vague: an unrecognised failure that says `KeyError: 'markets'`
    is still more useful to whoever debugs it than "an error occurred".
    """
    if isinstance(exc, asyncio.TimeoutError):
        return "no response before the deadline"

    if isinstance(exc, httpx.TimeoutException):
        return "the request timed out"

    if isinstance(exc, httpx.ConnectError):
        # DNS and refused connections both land here and mean different things
        # to whoever is fixing it.
        text = str(exc).lower()
        if "getaddrinfo" in text or "name or service" in text or "nodename" in text:
            return "the host could not be resolved (DNS)"
        return "the connection was refused"

    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"

    if isinstance(exc, httpx.HTTPError):
        return f"the request failed ({type(exc).__name__})"

    message = str(exc).strip()
    return message or type(exc).__name__


def is_rate_limited(status_code: int | None, body: str = "") -> bool:
    """Whether a response is a rate limit rather than a different refusal.

    Worth separating: a rate limit is temporary and the right consequence is
    "try again next tick", whereas a rejected credential needs an operator. A
    model told the same thing about both learns nothing from either.
    """
    if status_code == 429:
        return True
    lowered = (body or "").lower()
    return any(
        marker in lowered
        for marker in ("rate limit", "rate-limit", "too many requests", "throttl")
    )


def describe_age(seconds: float) -> str:
    """Human duration for staleness messages. Keeps the number."""
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    if seconds < 172_800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86_400:.1f}d"


__all__ = [
    "explain_exception",
    "is_rate_limited",
    "describe_age",
    "SKIPPED_TO_PROTECT_LATENCY",
    "TREAT_AS_STALE",
    "OTHERS_UNAFFECTED",
    "RETRY_NEXT_TICK",
    "NEEDS_OPERATOR",
    "DROPPED_NOT_SHOWN",
]
