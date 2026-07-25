"""Which protocols the agent can see. **Data, not code.**

This table is the concrete form of the Messari standardized-subgraph argument:
because every lending protocol answers the *same* GraphQL query shape, adding
one to the agent's opportunity set is a single line here. No adapter, no new
module, no schema change, no redeploy — the mandate's `allowed_assets` then
decides which of these markets actually get considered.

That is the whole claim, and it is checkable: `curator-data protocols` prints
this table, and `curator-data verify-live` queries every enabled row.

## Adding a protocol

1. Find it on https://thegraph.com/explorer — confirm it indexes **base** and
   uses the Messari standardized schema (its entities are `markets` /
   `liquidityPools`, not `reserves` / `pools`).
2. Copy the Subgraph ID from the Query URL (`/subgraphs/id/<THIS>`).
3. Add one `Protocol(...)` line below.
4. `curator-data verify-live --protocol <key>` to confirm it answers.

## Why `verified`

An ID alone does not tell you whether a subgraph follows the Messari schema or
its protocol's own. We cannot check that without a gateway credential, so each
row records whether it has been confirmed against the live gateway. Unverified
rows still ship — they simply degrade into `MarketSnapshot.errors` if the shape
is wrong, which is exactly the designed behaviour, and `verify-live` names the
offender rather than leaving a silent gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: Which query shape a subgraph answers.
#:
#: `lending` and `dex-amm` are Messari's standardized schemas — one shape per
#: protocol *type*, which is what lets one adapter serve many protocols.
#:
#: `lending-aave` is Aave's own schema. Verified by live introspection on
#: 2026-07-25: the published "Aave V3 Base" subgraph exposes `reserves`, not
#: `markets`, so the standardized query cannot read it. Aave is the largest
#: lending market on Base and worth a second shape — but it is served by a
#: SEPARATE SOURCE (`sources/aave.py`, registry key `aave`) rather than folded
#: into the Messari adapter, because `Fact.source` is provenance: labelling
#: data pulled from Aave's own subgraph as "messari" would be a lie to the UI.
SchemaFamily = Literal["lending", "dex-amm", "lending-aave"]


@dataclass(frozen=True)
class Protocol:
    """One queryable protocol deployment."""

    #: Stable identifier, used as `Fact.subject.protocol` and shown in the UI.
    key: str
    #: Subgraph ID from the Graph Explorer Query URL.
    subgraph_id: str
    family: SchemaFamily
    label: str
    chain: str = "base"
    #: Schema family confirmed against the live gateway? See module docstring.
    verified: bool = False
    #: Queried by default. Set False to keep a row documented but dormant.
    enabled: bool = True


# ── Lending markets — the composition story ───────────────────────────────
#
# One query shape, N protocols. Every row below is answered by the identical
# GraphQL document in messari.py; none of them needed a line of adapter code.

LENDING: tuple[Protocol, ...] = (
    Protocol(
        key="moonwell",
        subgraph_id="33ex1ExmYQtwGVwri1AP3oMFPGSce6YbocBP7fWbsBrg",
        family="lending",
        label="Moonwell (Base)",
        # Verified live 2026-07-25: 18 markets, USDC ~15.9% supply APY on
        # ~$14.5M TVL. This row is the standardized-schema proof.
        verified=True,
    ),
    # Rejected after live testing, recorded so nobody re-adds them:
    #   morpho-blue-base (71ZTy1ve…) answers the standardized shape but indexes
    #     spam markets — top market by TVL is $447 with symbols like
    #     "MINITIMEBOTALPHAXXX" and 0% rates. Unusable, not fixable here.
    #   aave-v3_base (8d78rQci…) and both Compound V3 Base subgraphs expose
    #     `markets` WITHOUT `inputToken`, so they are a different schema again,
    #     not merely an older Messari version.
    #   Seamless / ExtraFi expose no `markets` field at all.
)

# ── Aave, on its own schema ───────────────────────────────────────────────

AAVE: tuple[Protocol, ...] = (
    Protocol(
        key="aave-v3",
        subgraph_id="GQFbb95cE6d8mV989mL5figjaGaKCQB3xqYrr1bRyXqF",
        family="lending-aave",
        label="Aave V3 (Base)",
        # Verified live 2026-07-25: USDC ~3.4% supply APY on ~$175M supplied,
        # 0.84 utilization.
        verified=True,
    ),
)


# ── DEX pools — liquidity and volume for the market-making side ───────────

DEX: tuple[Protocol, ...] = (
    Protocol(
        key="uniswap-v3",
        subgraph_id="FUbEPQw1oMghy39fwWBFY5fE6MXPXZQtjncQy2cXdrNS",
        family="dex-amm",
        label="Uniswap V3 (Base)",
        # Live introspection 2026-07-25 confirms this IS Messari standardized
        # (`liquidityPools`, `dexAmmProtocol`) — the schema fallback is not
        # needed here. It is nonetheless failing at the network level:
        # the gateway returns `bad indexers: {0xe13840a2…}` after ~20s for any
        # page size. That is an indexer-availability problem on The Graph's
        # side, not a query problem, and it may clear on its own.
        #
        # Left ENABLED so it recovers automatically if the indexers do, and so
        # verify-live keeps reporting the truth about it. It degrades into
        # errors[] meanwhile and costs one timeout per snapshot.
        enabled=True,
        verified=True,
    ),
)


ALL: tuple[Protocol, ...] = LENDING + AAVE + DEX


def enabled_protocols(
    family: SchemaFamily | None = None, chain: str | None = None
) -> list[Protocol]:
    """Protocols to query, optionally narrowed by family and chain."""
    return [
        p
        for p in ALL
        if p.enabled
        and (family is None or p.family == family)
        and (chain is None or p.chain == chain)
    ]


def by_key(key: str) -> Protocol | None:
    return next((p for p in ALL if p.key == key), None)


__all__ = ["Protocol", "SchemaFamily", "LENDING", "DEX", "ALL", "enabled_protocols", "by_key"]
