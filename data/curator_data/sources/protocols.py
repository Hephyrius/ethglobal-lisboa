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

#: Which query shape a subgraph answers. Messari publishes one standardized
#: schema per protocol *type*, so this is a small closed set rather than a
#: per-protocol concern — that is precisely what makes the table extensible.
SchemaFamily = Literal["lending", "dex-amm"]


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
        key="aave-v3",
        subgraph_id="GQFbb95cE6d8mV989mL5figjaGaKCQB3xqYrr1bRyXqF",
        family="lending",
        label="Aave V3 (Base)",
    ),
    Protocol(
        key="moonwell",
        subgraph_id="33ex1ExmYQtwGVwri1AP3oMFPGSce6YbocBP7fWbsBrg",
        family="lending",
        label="Moonwell (Base)",
    ),
)


# ── DEX pools — liquidity and volume for the market-making side ───────────

DEX: tuple[Protocol, ...] = (
    Protocol(
        key="uniswap-v3",
        subgraph_id="FUbEPQw1oMghy39fwWBFY5fE6MXPXZQtjncQy2cXdrNS",
        family="dex-amm",
        label="Uniswap V3 (Base)",
        # Published by Uniswap rather than Messari, so it may answer the
        # official `pools` schema instead of the standardized `liquidityPools`.
        # Left enabled deliberately: if the shape is wrong it degrades into
        # errors[] and verify-live names it, which is more useful than an
        # untested row we never look at.
        enabled=True,
    ),
)


ALL: tuple[Protocol, ...] = LENDING + DEX


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
