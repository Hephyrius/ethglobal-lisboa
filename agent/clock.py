"""Time, in the one format that survives the Python → TypeScript boundary.

This module exists because of a real, silent interoperability trap.

Lane E validates every API response with zod, and `z.string().datetime()` accepts
**only** UTC with a `Z` suffix by default — it rejects both a bare naive timestamp
and a numeric offset like `+02:00`. Pydantic serializes whatever it is given:

    datetime(2026, 7, 25, 14, 5, 7, tzinfo=utc)  ->  "2026-07-25T14:05:07Z"   ok
    datetime(2026, 7, 25, 14, 5, 7)              ->  "2026-07-25T14:05:07"    rejected
    datetime.now()  on a Lisbon machine (UTC+1)  ->  "...+01:00"              rejected

So a plain `datetime.now()` anywhere in this lane produces a payload that passes
every Python test and then fails in the browser, at the demo, with a zod error
pointing at the field rather than the cause. Every timestamp the harness mints
goes through `utcnow()`, and `test_api_routes.py` asserts the `Z` suffix on the
wire so a regression fails here instead of in Lane E.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["utcnow", "to_utc", "isoformat_z"]


def utcnow() -> datetime:
    """Now, timezone-aware in UTC. The only clock this lane reads."""
    return datetime.now(UTC)


def to_utc(value: datetime) -> datetime:
    """Normalize any datetime to timezone-aware UTC.

    A naive datetime is *assumed* to be UTC rather than local time. That is the
    right assumption here: naive values reaching this function come from parsed
    fixtures and external payloads that are UTC by convention, and guessing local
    time would shift them by the host's offset — a bug that changes value with
    the machine it runs on.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def isoformat_z(value: datetime) -> str:
    """RFC 3339 in UTC with a `Z` suffix — the shape zod's `.datetime()` accepts."""
    return to_utc(value).isoformat().replace("+00:00", "Z")
