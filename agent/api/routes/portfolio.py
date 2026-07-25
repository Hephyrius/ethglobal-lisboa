"""`GET /portfolio/{owner}` — one wallet's position across every vault.

Not one of the frozen Wave 0 routes. It exists because the dApp could answer
"how is this vault doing?" and had no way to answer **"how am I doing?"**, which
is the first thing a depositor with money in more than one vault wants to know.

Returns exact figures only: shares held, current worth via the vault's own
`convertToAssets`, and each vault's return since inception. Deliberately **no
P&L** — see `agent/portfolio/reader.py` for why a cost basis is a good way to be
quietly wrong about someone's money.
"""

from __future__ import annotations

import logging
import re
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from ...portfolio import read_portfolio

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

log = logging.getLogger(__name__)

_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")


class PositionOut(BaseModel):
    vault: str
    symbol: str
    shares: str
    value_in_asset: str
    asset_decimals: int
    #: The VAULT's return since inception, not the holder's. A depositor who
    #: entered later has not earned this, and the field name has to say so.
    vault_return_pct: float | None = None


class PortfolioOut(BaseModel):
    owner: str
    positions: list[PositionOut] = Field(default_factory=list)
    total_value: str
    asset_decimals: int


@router.get("/{owner}", response_model=PortfolioOut, response_model_exclude_none=True)
async def portfolio(
    owner: Annotated[str, Path(description="Wallet address, 0x-prefixed, 40 hex characters.")],
) -> PortfolioOut:
    """Every vault where this wallet holds shares, largest first.

    An empty list is a real and common answer — a wallet that has not deposited
    anywhere. It is not an error, and the dApp renders it as "no positions yet"
    rather than as a failure.
    """
    if not _ADDRESS.match(owner):
        raise HTTPException(status_code=422, detail=f"{owner!r} is not a 0x-prefixed address")

    from ...config import settings
    from ..deps import get_vault_service

    del get_vault_service  # portfolio reads the chain directly; see the module note

    config = settings()
    factory = _factory_address()
    if factory is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "no VaultFactory address is available, so there are no vaults to look in. "
                "Deploy first, or set FACTORY_ADDRESS."
            ),
        )

    from curator_data.chain.rpc import RpcClient

    rpc = RpcClient(config.rpc_url, timeout_s=20.0)
    try:
        result = await read_portfolio(rpc, factory, owner)
    except Exception as exc:  # noqa: BLE001 - an unreachable node is a 503, not a 500
        log.warning("portfolio read failed for %s: %s", owner, exc)
        raise HTTPException(
            status_code=503, detail=f"could not read the chain at {config.rpc_url}: {exc}"
        ) from exc
    finally:
        await rpc.aclose()

    return PortfolioOut(
        owner=result.owner,
        positions=[PositionOut(**vars(p)) for p in result.positions],
        total_value=result.total_value,
        asset_decimals=result.asset_decimals,
    )


def _factory_address() -> str | None:
    """Configured factory, else the deployment manifest Lane A publishes."""
    import json
    from pathlib import Path

    from ...config import settings

    if configured := settings().factory_address:
        return configured

    manifest = Path("deployments/base-fork.json")
    if not manifest.is_file():
        return None
    try:
        return (json.loads(manifest.read_text(encoding="utf-8")).get("contracts") or {}).get(
            "VaultFactory"
        )
    except (OSError, ValueError):
        return None
