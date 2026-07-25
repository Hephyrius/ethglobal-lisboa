"""`GET /venues` — Lane D's capability manifest, over HTTP (cross-lane #73).

    GET /venues -> [{key, role, summary, intents[], tokens[], custody,
                     custody_note, requires[], available, unavailable_reason, …}]

Lane D built the manifest and it is reachable from Python (`from venues import
manifest`), but nothing served it, so the browser could not see it and Lane E's
venue strip had to degrade to bare keys from `/genesis/sources`. This is the
whole route: resolve, call, return.

## Two decisions worth stating

**The payload is not re-modelled, deliberately.** The manifest is Lane D's own
shape and explicitly *not* part of the frozen interface — which is what lets
them extend it without a schema request (#70). Declaring a pydantic
`response_model` here would strip any key this file did not anticipate, so the
next field Lane D adds would vanish silently between two lanes that both
believed they had shipped it. Lane E parses with a `.passthrough()` schema for
the same reason. The one thing this route guarantees is the *envelope*: a JSON
array, unwrapped, exactly as asked for.

**An unreachable manifest is a 503, not an empty array.** Lane E already built
and tested a degraded state that says capability detail is unavailable, and
`[]` would mean "there are no venues" — a different and false claim that would
render as an empty strip. A status code they can branch on is more useful than
a body they have to interpret.

The manifest does no network I/O (#61), so it is safe to call per request and
needs no cache.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ...config import Settings
from ...providers.resolve import resolve_ref
from ..deps import get_settings

router = APIRouter(tags=["venues"])

Config = Annotated[Settings, Depends(get_settings)]

log = logging.getLogger(__name__)


def _manifest(config: Settings) -> list[dict[str, Any]]:
    """Resolve and call Lane D's manifest, or raise a 503 naming the ref.

    Resolved late through a config ref like every other cross-lane seam here —
    a module-scope `from venues import manifest` would make this component fail
    to import when Lane D is absent, which is the coupling the whole late-binding
    pattern exists to avoid.
    """
    ref = config.venue_manifest_ref
    try:
        entries = resolve_ref(ref)
    except Exception as exc:  # noqa: BLE001 - venues is an optional seam
        log.warning("venue manifest ref %r did not resolve (%s)", ref, exc)
        raise HTTPException(
            status_code=503,
            detail=(
                f"the venue capability manifest is unavailable: {ref} did not resolve ({exc}). "
                "Venue keys are still listed by GET /genesis/sources."
            ),
        ) from exc

    if not isinstance(entries, list):
        # A ref that resolves to the wrong thing is a misconfiguration, and
        # saying so beats returning whatever it happened to be.
        raise HTTPException(
            status_code=503,
            detail=f"{ref} returned {type(entries).__name__}, expected a list of venue entries",
        )
    return entries


@router.get("/venues")
async def venues(config: Config) -> list[dict[str, Any]]:
    """What each venue can do, and whether it is usable right now.

    Returned unwrapped and unmodelled — see the module docstring. `available`
    is the field to branch on: a venue missing a credential is listed with
    `available: false` and an `unavailable_reason` rather than being hidden,
    so the UI can say *why* something cannot be used.
    """
    return _manifest(config)
