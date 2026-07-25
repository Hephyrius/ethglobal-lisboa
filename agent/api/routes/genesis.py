"""The two frozen genesis routes, plus the source list the picker needs.

    POST /genesis/chat      {messages[]} -> {reply, mandate_draft?}
    POST /genesis/finalize  {mandate}    -> {mandate_hash, deploy_tx, vault}
    GET  /genesis/sources                -> {sources[], venues[]}

Genesis is a one-time event: it produces the mandate, and afterwards the human
deployer cannot change it — only the agent can (locked decision,
plans/initiate_plan.md §2). `finalize` is therefore the irreversible step, and
the hash it returns is what the vault is permanently bound to.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ...service.ports import GenesisService
from ..deps import get_genesis_service
from ..schemas import (
    GenesisChatRequest,
    GenesisChatResponse,
    GenesisFinalizeRequest,
    GenesisFinalizeResponse,
    SourcesResponse,
)

router = APIRouter(prefix="/genesis", tags=["genesis"])

Service = Annotated[GenesisService, Depends(get_genesis_service)]


@router.post("/chat", response_model=GenesisChatResponse, response_model_exclude_none=True)
async def genesis_chat(body: GenesisChatRequest, service: Service) -> GenesisChatResponse:
    """One turn of the strategy conversation.

    `mandate_draft` is a preview of what has been pinned down so far. It is
    advisory and may be partial or absent — nothing is committed until
    `finalize`.
    """
    return await service.chat(body.messages)


@router.post(
    "/finalize", response_model=GenesisFinalizeResponse, response_model_exclude_none=True
)
async def genesis_finalize(
    body: GenesisFinalizeRequest, service: Service
) -> GenesisFinalizeResponse:
    """Crystallize the mandate and deploy its vault.

    The request body is validated against the full frozen `Mandate` schema
    before anything is deployed, so an incomplete draft is rejected here with a
    422 rather than producing a vault bound to a nonsense mandate.

    `mandate_hash` is keccak256 over the canonical serialization
    (`agent/mandate/hashing.py`) and is identical in fixture and live mode — the
    value shown to the user is the value committed on-chain.
    """
    return await service.finalize(body.mandate)


@router.get("/sources", response_model=SourcesResponse)
async def genesis_sources(service: Service) -> SourcesResponse:
    """What the user may grant this agent.

    Not one of the five frozen routes. The genesis flow requires the user to
    choose which data sources the agent may consult, and that list has to come
    from whatever Lane C has actually registered — a list hardcoded in the dApp
    would rot the moment a source is added or renamed.
    """
    return SourcesResponse(
        sources=service.available_sources(), venues=service.available_venues()
    )
