"""The three frozen vault routes, plus the mandate read Lane E asked for.

    GET  /vault/{addr}/state              -> VaultState
    GET  /vault/{addr}/decisions?limit=   -> AgentAction[]
    POST /vault/{addr}/tick               -> AgentAction
    GET  /vault/{addr}/mandate            -> Mandate           (cross-lane request #5)
    GET  /vault/{addr}/mandate/verification -> MandateVerificationResponse (#71)
    GET  /vault/{addr}/performance?window= -> VaultPerformance (Wave 1 P2)

`response_model_exclude_none=True` on every route is load-bearing, not tidiness:
zod's `.optional()` accepts a missing key but **rejects** an explicit `null`, so
serializing pydantic's unset optionals would fail in Lane E's browser while
passing every Python test here. See `agent/api/schemas.py`.
"""

from __future__ import annotations

import re
from typing import Annotated

from curator_schema import AgentAction, Mandate, VaultPerformance, VaultState
from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ...performance.window import WINDOWS
from ...service.ports import VaultService
from ..deps import get_vault_service
from ..schemas import MandateVerificationResponse

router = APIRouter(prefix="/vault", tags=["vault"])

_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")

#: Documented in the OpenAPI schema and validated before any service call, so a
#: typo'd address fails with a readable 422 rather than an RPC error 30 seconds
#: later.
VaultAddress = Annotated[
    str,
    Path(description="Vault contract address, 0x-prefixed and 40 hex characters."),
]


def _checked(addr: str) -> str:
    if not _ADDRESS.match(addr):
        raise HTTPException(status_code=422, detail=f"{addr!r} is not a 0x-prefixed address")
    return addr


Service = Annotated[VaultService, Depends(get_vault_service)]


@router.get("/{addr}/state", response_model=VaultState, response_model_exclude_none=True)
async def vault_state(addr: VaultAddress, service: Service) -> VaultState:
    return await service.state(_checked(addr))


@router.get(
    "/{addr}/decisions", response_model=list[AgentAction], response_model_exclude_none=True
)
async def vault_decisions(
    addr: VaultAddress,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[AgentAction]:
    """Recent decision cycles, newest first.

    Includes `rejected` and `failed` actions deliberately — they are the record
    that output validation stopped something, and the feed is more honest with
    them than without.
    """
    return await service.decisions(_checked(addr), limit)


@router.post("/{addr}/tick", response_model=AgentAction, response_model_exclude_none=True)
async def vault_tick(addr: VaultAddress, service: Service) -> AgentAction:
    """Run one decision cycle.

    A cycle that holds, is rejected at validation, or reverts on-chain is a
    successful *request* returning an AgentAction that says so. This route only
    returns an error status if the harness itself could not run.
    """
    return await service.tick(_checked(addr))


@router.get(
    "/{addr}/performance",
    response_model=VaultPerformance,
    response_model_exclude_none=True,
)
async def vault_performance(
    addr: VaultAddress,
    service: Service,
    window: Annotated[str, Query(description=f"One of: {', '.join(WINDOWS)}")] = "all",
) -> VaultPerformance:
    """Share-price history and the risk figures derived from it.

    Points are observations, never interpolations — on a pinned fork blocks are
    mined only when a transaction lands, so a flat stretch between two trades is
    the truth and the chart should not smooth it.

    Every figure in `summary` is nullable and is **null, not zero**, when the
    series is too short to support it. Render "not enough history" for a null;
    rendering 0.0% would be a claim we cannot make.
    """
    if window.lower() not in WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown window {window!r}; expected one of {sorted(WINDOWS)}",
        )
    return await service.performance(_checked(addr), window.lower())


@router.get("/{addr}/mandate", response_model=Mandate, response_model_exclude_none=True)
async def vault_mandate(addr: VaultAddress, service: Service) -> Mandate:
    """The mandate this vault is curated under.

    Added for cross-lane request #5: `VaultState` carries only `mandate_hash`,
    so without this the dApp cannot render the mandate viewer for a vault the
    browser did not itself create.
    """
    return await service.mandate(_checked(addr))


@router.get(
    "/{addr}/mandate/verification",
    response_model=MandateVerificationResponse,
    response_model_exclude_none=True,
)
async def vault_mandate_verification(
    addr: VaultAddress, service: Service
) -> MandateVerificationResponse:
    """Does this vault's mandate still hash to what the chain recorded?

    Added for cross-lane request #71. The dApp's docs drawer claims *"the keccak
    hash is the depositor's entire verification handle"*, and that claim went
    conditional the moment the schema gained a field with a non-`None` default:
    a vault deployed before `tolerance_band_pct` no longer reproduces its own
    hash, because the field materializes when the stored mandate is parsed.

    Rather than engineer the digest to keep matching — which would make the
    on-chain hash assert something untrue, since such a vault really is being
    run under a constraint it never agreed to — this route separates the three
    reasons a recompute can differ and says which one applies. Only the last is
    alarming: schema drift, an agent amendment, or an unexplained mismatch.
    """
    return await service.mandate_verification(_checked(addr))
