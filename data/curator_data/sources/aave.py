"""Aave V3 via Aave's own subgraph schema.

**This module is the extension point being used, not described.** It was added
after the Messari adapter shipped, in one file plus one line in
`sources/__init__.py`. Nothing in `registry.py`, `facts.py`, `queries.py`, the
MCP server or the frozen schema changed to accommodate it — which is the
property the whole data layer exists to have.

## Why Aave needs its own source rather than a branch in `messari.py`

Live introspection (2026-07-25) showed the published "Aave V3 Base" subgraph
exposes `reserves`, not the Messari standardized `markets`. It could have been
a second query shape inside the Messari adapter, but `Fact.source` is
*provenance* — the string the dApp shows under "where did this number come
from". Labelling data pulled from Aave's own subgraph as `messari` would be
false. A separate key is both more honest and less code.

## Unit traps, all verified against live values

Aave's schema is not normalised the way Messari's is:

  * **`liquidityRate` is an APR in RAY** (1e27 fixed point). USDC read
    `3410…e24` → 0.0341 → 3.41%. Divided by 1e27 here.
  * **`utilizationRate` is already a decimal ratio** — no scaling — but it can
    come back **negative** (USDbC read `-3.4406`). Those are dropped rather
    than clamped: clamping -3.44 to 0 would assert "this market has no
    borrowing", which is a claim, not a repair.
  * **`price.priceInEth` actually holds USD with 8 decimals**, despite the
    name. USDC read `99990000` → $0.9999; cbBTC read `6675885000000` →
    $66,758.85. A well-known misnomer in Aave's subgraph.
"""

from __future__ import annotations

import logging
from typing import Any

from curator_schema.models import Fact

from ..config import Settings
from ..diagnostics import OTHERS_UNAFFECTED, explain_exception
from ..facts import FactBuilder
from ..graph.factory import make_gateway
from ..graph.gateway import GatewayClient
from ..ports import BaseSource
from .protocols import Protocol, enabled_protocols

logger = logging.getLogger(__name__)

RAY = 1e27
#: `price.priceInEth` is USD in 8-decimal fixed point (see module docstring).
PRICE_SCALE = 1e8
RESERVE_LIMIT = 100

#: A utilization outside this range is corrupt rather than extreme, and the
#: fact is dropped. Slight overshoot above 1.0 is real (accrued interest), so
#: the ceiling is not exactly 1.
UTILIZATION_BOUNDS = (0.0, 1.5)

RESERVES_QUERY = """
query CuratorAaveReserves($first: Int!) {
  reserves(first: $first, where: { isActive: true }) {
    symbol
    decimals
    isFrozen
    liquidityRate
    utilizationRate
    totalATokenSupply
    price { priceInEth }
  }
}
"""


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class AaveSource(BaseSource):
    """Supply APY, utilization and TVL for Aave V3 markets."""

    key = "aave"
    provides = ("yield", "tvl", "utilization")
    description = (
        "Aave V3 supply APYs, utilization and TVL on Base, read from Aave's own "
        "subgraph on The Graph. Separate from the Messari adapter because Aave "
        "publishes its own schema rather than the standardized one."
    )

    def __init__(
        self,
        settings: Settings,
        *,
        gateway: GatewayClient | None = None,
        protocols: list[Protocol] | None = None,
    ):
        super().__init__()
        self.settings = settings
        self._gateway = gateway or make_gateway(settings)
        self._owns_gateway = gateway is None
        self._protocols = (
            protocols
            if protocols is not None
            else enabled_protocols(family="lending-aave", chain=settings.chain)
        )

    async def fetch(self, assets: list[str]) -> list[Fact]:
        wanted = {a.strip().upper() for a in assets if a and a.strip()}
        if not self._protocols:
            return []
        if not self.settings.graph_api_key:
            raise RuntimeError(
                "GRAPH_API_KEY is not set - every Aave market is unreadable this tick, and "
                "no retry will fix it. Get one free at https://thegraph.com/studio -> API Keys "
                "and put it in .env"
            )

        facts: list[Fact] = []
        for protocol in self._protocols:
            try:
                facts.extend(await self._fetch_protocol(protocol, wanted))
            except Exception as exc:  # noqa: BLE001 - one deployment must not sink the rest
                # `OTHERS_UNAFFECTED` matters more than it looks: this source
                # can serve several deployments, and without it one failure
                # reads as "Aave is down" rather than "one deployment is".
                self.diagnose(protocol.key, explain_exception(exc), OTHERS_UNAFFECTED)
        return facts

    async def _fetch_protocol(self, protocol: Protocol, wanted: set[str]) -> list[Fact]:
        data = await self._gateway.query(
            protocol.subgraph_id, RESERVES_QUERY, {"first": RESERVE_LIMIT}
        )
        builder = FactBuilder(self.key, chain=protocol.chain, on_finding=self.diagnose)
        facts: list[Fact] = []
        matched = 0

        for reserve in data.get("reserves") or []:
            symbol = str(reserve.get("symbol") or "").upper()
            if wanted and symbol not in wanted:
                continue
            # A frozen reserve still reports a rate, but nothing can be
            # supplied to it. Offering it as an option would be wrong.
            if reserve.get("isFrozen"):
                continue
            matched += 1
            subject = builder.subject(protocol=protocol.key, market=symbol)

            apy = self._supply_apy(reserve)
            if apy is not None:
                facts.append(builder.apy_from_fraction(subject, apy))

            utilization = self._utilization(reserve)
            if utilization is not None:
                facts.append(builder.ratio("utilization", subject, utilization))

            tvl = self._tvl_usd(reserve)
            if tvl is not None:
                facts.append(builder.usd("tvl", subject, tvl))

        if wanted and not matched:
            # Not a failure: the query worked, this protocol simply does not
            # list the asset. `remark` keeps it out of "data you could not read".
            self.diagnose(
                protocol.key,
                f"no active reserve for {sorted(wanted)} among the first {RESERVE_LIMIT}",
                "this protocol is not an option for those assets this tick",
                failure=False,
            )
        return facts

    @staticmethod
    def _supply_apy(reserve: dict) -> float | None:
        """`liquidityRate` is an APR in RAY. Returns a fraction."""
        rate = _to_float(reserve.get("liquidityRate"))
        return None if rate is None else rate / RAY

    @staticmethod
    def _utilization(reserve: dict) -> float | None:
        """Already a ratio, but occasionally corrupt — see module docstring."""
        value = _to_float(reserve.get("utilizationRate"))
        if value is None:
            return None
        low, high = UTILIZATION_BOUNDS
        if not (low <= value <= high):
            return None
        return min(value, 1.0)

    @staticmethod
    def _tvl_usd(reserve: dict) -> float | None:
        """Supplied tokens x USD price. Both need scaling; neither is obvious."""
        supply = _to_float(reserve.get("totalATokenSupply"))
        decimals = reserve.get("decimals")
        price_raw = _to_float((reserve.get("price") or {}).get("priceInEth"))
        if supply is None or price_raw is None or decimals is None:
            return None
        try:
            tokens = supply / (10 ** int(decimals))
        except (TypeError, ValueError):
            return None
        usd = tokens * (price_raw / PRICE_SCALE)
        return usd if usd > 0 else None

    async def close(self) -> None:
        if self._owns_gateway:
            await self._gateway.aclose()


def make_aave_source(settings: Settings) -> AaveSource:
    """Registration factory. Referenced from `sources/__init__.py`."""
    return AaveSource(settings)


__all__ = ["AaveSource", "make_aave_source", "RESERVES_QUERY"]
