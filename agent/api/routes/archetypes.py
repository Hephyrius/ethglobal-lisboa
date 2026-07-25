"""One click, a strategy nobody wrote, on-chain.

    GET  /archetypes                 -> [ArchetypeSummary]
    POST /archetypes/{key}/deploy    -> ArchetypeDeployResponse

Distinct from `/genesis` in the one way that matters: **there is no human in
this loop.** Genesis is a conversation someone reads before finalizing, and its
`finalize` takes a mandate the user has seen. Here the model writes the mandate
and the vault is deployed unread, so the envelope check in
`agent/archetypes/generate.py` is the entire review process — the same argument
that makes `agent/model/validation.py` load-bearing, applied one step earlier.

Both routes are new; neither is one of the five frozen ones.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ...archetypes import GenerationFailed
from ...service.ports import ArchetypeService
from ..deps import get_archetype_service
from ..schemas import ArchetypeDeployRequest, ArchetypeDeployResponse, ArchetypeSummary

router = APIRouter(prefix="/archetypes", tags=["archetypes"])

log = logging.getLogger(__name__)

Service = Annotated[ArchetypeService, Depends(get_archetype_service)]


@router.get("", response_model=list[ArchetypeSummary])
def list_archetypes(service: Service) -> list[ArchetypeSummary]:
    """Every envelope the dApp may offer as a card.

    Served from the API as well as being importable from `@curator/schema`
    because the two answer different questions: the package has the bounds, and
    this has `deployed`, which is per-deployment state no static file can carry.
    A card that says *"3 vaults so far"* needs the running system.
    """
    return service.summaries()


@router.post(
    "/{key}/deploy",
    response_model=ArchetypeDeployResponse,
    response_model_exclude_none=True,
)
async def deploy_archetype(
    key: str, service: Service, body: ArchetypeDeployRequest | None = None
) -> ArchetypeDeployResponse:
    """Generate a mandate inside this archetype's bounds and deploy its vault.

    The body is optional so the button works before a wallet is connected —
    `deployer` is the only thing it can carry, it is asserted rather than
    proven, and a missing one costs attribution, not the deployment.

    **422 means nothing was deployed.** A generation that escaped its envelope is
    regenerated and, if the attempts run out, refused: there is no version of
    this route that puts an out-of-bounds mandate on-chain, because the card's
    promise is the only description of the vault anyone will ever read.
    """
    try:
        return await service.deploy(key, body.deployer if body else None)
    except KeyError as exc:
        # `load_archetype` raises with the available keys in the message, which
        # is the useful half of a 404 here.
        raise HTTPException(status_code=404, detail=str(exc).strip("\"'")) from exc
    except GenerationFailed as exc:
        log.warning("archetype %s produced nothing deployable: %s", key, exc)
        raise HTTPException(
            status_code=422,
            detail=(
                f"{exc} — nothing was deployed. A mandate outside its archetype's "
                f"bounds is never put on-chain, because nobody reads it first."
            ),
        ) from exc
