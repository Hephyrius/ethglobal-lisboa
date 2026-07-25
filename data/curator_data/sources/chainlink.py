"""Chainlink price feeds, read on-chain.

The fourth source, and the first that is not an HTTP API. That is deliberate:
every previous source proved the registry can merge *endpoints*, and this one
proves it merges *kinds of provider*. A contract read and a GraphQL query land
in the same `MarketSnapshot`, and neither knows the other exists.

## Why Chainlink rather than a price API

1. **The vault already prices holdings this way.** `totalAssets()` values
   non-base holdings through `ChainlinkPriceLib.sol`. If the agent priced WETH
   from some API while the contract priced it from Chainlink, the two would
   disagree about what the portfolio is worth, and the agent could compute a
   rebalance the vault then values differently. One oracle, no drift.
2. **The mandate already constrains to it.** The golden mandate's
   `update_rules` permits widening `allowed_assets` *"only to assets with a
   Chainlink Base feed"* — so this source covers, by construction, every asset
   the mandate can ever permit.
3. **No credential and no rate limit** — an `eth_call` against an RPC we
   already have, so price facts survive a missing or exhausted API key.

It does not *replace* `token_api`: that one derives price from executed swaps,
which is a mechanically independent measurement. Live, the two agreed within
0.1% ($1,858.98 oracle vs $1,857.95 swap-derived). Registering both means a
disagreement between them is itself a signal the curator can act on.

## Correctness rails

A wrong price here is expensive, so the checks are not decoration:

  * **Feed identity is verified once per process** against `description()`.
    A wrong address does not error — it returns a confident, well-formed,
    completely wrong number.
  * **`updatedAt` becomes `Fact.observed_at`**, not the time we asked. The
    frozen schema is explicit that staleness is the agent's to reason about,
    and that only works if we report when the *oracle* last spoke.
  * **A non-positive answer is dropped.** `latestRoundData` returns a signed
    int; a zero or negative USD price is a broken feed, not a cheap asset.
  * **An incomplete round is dropped** (`answeredInRound < roundId`).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from curator_schema.models import Fact

from ..chain.rpc import RpcClient, RpcError, decode_string, decode_word
from ..config import Settings
from ..facts import FactBuilder
from ..ports import BaseSource
from .feeds import PriceFeed, feeds_for, known_symbols

logger = logging.getLogger(__name__)

# Argument-free view selectors, each verified with keccak (see tests).
SELECTOR_LATEST_ROUND_DATA = "0xfeaf968c"
SELECTOR_DECIMALS = "0x313ce567"
SELECTOR_DESCRIPTION = "0x7284e416"

#: Beyond this, a feed is stale enough to be worth flagging. Chainlink's USD
#: feeds on Base have heartbeats well inside a day; a price older than this is
#: a signal in itself, so it is reported rather than silently used.
STALE_AFTER_S = 24 * 3600


class ChainlinkSource(BaseSource):
    """USD prices from Chainlink aggregators."""

    key = "chainlink"
    provides = ("price",)
    description = (
        "USD spot prices from Chainlink price feeds on Base, read on-chain. The same "
        "oracle the vault values its holdings with, so the agent and the contract "
        "cannot disagree about what the portfolio is worth. Needs no API key."
    )

    def __init__(
        self,
        settings: Settings,
        *,
        rpc: RpcClient | None = None,
        feeds: tuple[PriceFeed, ...] | None = None,
    ):
        super().__init__()
        self.settings = settings
        self._rpc = rpc
        self._owns_rpc = rpc is None
        self._feeds = feeds if feeds is not None else feeds_for(settings.chain)
        #: address -> decimals, and the set of addresses whose identity we have
        #: already confirmed. Neither changes within a run.
        self._decimals: dict[str, int] = {}
        self._verified: set[str] = set()

    @property
    def rpc(self) -> RpcClient:
        if self._rpc is None:
            if not self.settings.rpc_url:
                raise RuntimeError(
                    "no RPC endpoint configured - set DATA_RPC_URL, ANVIL_RPC_URL or "
                    "BASE_RPC_URL so Chainlink feeds can be read on-chain"
                )
            self._rpc = RpcClient(
                self.settings.rpc_url, timeout_s=self.settings.request_timeout_s
            )
        return self._rpc

    async def fetch(self, assets: list[str]) -> list[Fact]:
        wanted = {a.strip().upper() for a in assets if a and a.strip()}
        builder = FactBuilder(self.key, chain=self.settings.chain)

        facts: list[Fact] = []
        for feed in self._feeds:
            if wanted and feed.symbol.upper() not in wanted:
                continue
            try:
                fact = await self._read_feed(feed, builder)
            except RpcError as exc:
                self.note(f"{feed.symbol}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - one feed must not sink the rest
                self.note(f"{feed.symbol}: {type(exc).__name__}: {exc}")
                continue
            if fact is not None:
                facts.append(fact)

        missing = wanted - {f.symbol.upper() for f in self._feeds}
        if missing:
            self.note(
                f"no Chainlink feed configured for {sorted(missing)} on "
                f"{self.settings.chain} (have: {', '.join(known_symbols(self.settings.chain))}) - "
                f"add it to curator_data/sources/feeds.py"
            )
        return facts

    async def _read_feed(self, feed: PriceFeed, builder: FactBuilder) -> Fact | None:
        await self._verify_identity(feed)
        decimals = await self._feed_decimals(feed)

        data = await self.rpc.call(feed.address, SELECTOR_LATEST_ROUND_DATA)
        round_id = decode_word(data, 0)
        answer = decode_word(data, 1, signed=True)
        updated_at = decode_word(data, 3)
        answered_in_round = decode_word(data, 4)

        if answer <= 0:
            self.note(f"{feed.symbol}: feed returned a non-positive answer ({answer}) - ignored")
            return None
        if answered_in_round < round_id:
            self.note(f"{feed.symbol}: round {round_id} is incomplete - ignored")
            return None

        price = answer / (10**decimals)
        observed = datetime.fromtimestamp(updated_at, tz=timezone.utc) if updated_at else None

        if updated_at:
            age = datetime.now(timezone.utc).timestamp() - updated_at
            if age > STALE_AFTER_S:
                self.note(
                    f"{feed.symbol}: price is {age / 3600:.1f}h old - the agent should treat "
                    f"it as stale"
                )

        # observed_at is when the ORACLE last spoke, not when we asked.
        return builder.usd(
            "price", builder.subject(token=feed.symbol), price, observed_at=observed
        )

    async def _verify_identity(self, feed: PriceFeed) -> None:
        """Confirm the contract says it is the feed we think it is.

        Once per process. A wrong address is the failure mode with no symptom
        other than a wrong number, so this is worth one extra call.
        """
        if feed.address in self._verified:
            return
        described = decode_string(await self.rpc.call(feed.address, SELECTOR_DESCRIPTION))
        if described.strip().lower() != feed.expect_description.strip().lower():
            raise RpcError(
                f"feed at {feed.address} reports itself as {described!r}, not "
                f"{feed.expect_description!r} - wrong address, refusing to price with it"
            )
        self._verified.add(feed.address)

    async def _feed_decimals(self, feed: PriceFeed) -> int:
        cached = self._decimals.get(feed.address)
        if cached is not None:
            return cached
        decimals = decode_word(await self.rpc.call(feed.address, SELECTOR_DECIMALS), 0)
        if not 0 <= decimals <= 36:
            raise RpcError(f"implausible decimals ({decimals}) from {feed.address}")
        self._decimals[feed.address] = decimals
        return decimals

    async def close(self) -> None:
        if self._rpc is not None and self._owns_rpc:
            await self._rpc.aclose()


def make_chainlink_source(settings: Settings) -> ChainlinkSource:
    """Registration factory. Referenced from `sources/__init__.py`."""
    return ChainlinkSource(settings)


__all__ = ["ChainlinkSource", "make_chainlink_source", "STALE_AFTER_S"]
