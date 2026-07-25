"""Other vaults, as a data source.

Every other source answers "what is the market paying?". This one answers **"how
is everyone else doing?"** — and it is the only source whose facts are about
agents rather than about markets.

    peers:yield:vault/sambankmanvault      annualised return of a rival
    peers:volatility:vault/sambankmanvault its realised drawdown
    peers:tvl:vault/sambankmanvault        how much capital trusts it

## Why this is worth having, and not just cute

A curator with a mandate and no peers has no way to know whether 3 bps a day is
good. A curator that can see a rival vault running the same base asset at half
its drawdown has learned something real and verifiable — the numbers come from
`VaultFactory.vaults()` and each vault's own `convertToAssets`, not from a
leaderboard someone could game.

It also makes the demo's most interesting sentence possible: *"the conservative
USDC vault is beating me with half my drawdown, so I am widening my cooldown."*
That is an agent revising its own behaviour against evidence, which is the thing
the whole project is arguing an agent can do.

## The risk, stated rather than discovered

**Reflexivity.** If every vault copies the leader, the leader's edge becomes the
crowd, and the correlation between vaults that looked independent goes to one at
exactly the wrong moment. That is a real failure mode of copy-trading and it is
not hypothetical at scale.

Three things keep it bounded here, and none of them is "we hope it does not
happen":

1. **Peer facts are advisory.** Every mandate constraint still binds — a vault
   cannot copy its way past its own cash floor or position ceiling.
2. **Only outcomes cross, never positions.** This source reports return,
   drawdown and size. It does *not* report what a peer currently holds, so it
   cannot be used to mirror a book tick by tick.
3. **The mandate is the gate.** A vault whose `permitted_data_sources` omits
   `peers` never sees any of this, and that is a decision made at genesis by the
   person whose money it is.

Point 2 is the load-bearing one. Publishing allocations would make herding one
prompt away; publishing results makes it an argument the agent has to reason
through.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Final

from curator_schema.models import Fact

from ..chain.rpc import RpcClient, RpcError, decode_string, decode_word
from ..config import Settings
from ..facts import FactBuilder
from ..ports import BaseSource

logger = logging.getLogger(__name__)

#: Selectors, each computed with keccak and asserted in the tests. A wrong one
#: does not error — `eth_call` to a missing function on a contract with no
#: fallback returns `0x`, which reads as "no such vault".
SELECTOR_VAULTS: Final[str] = "0x8220ef5b"  # VaultFactory.vaults()
SELECTOR_TOTAL_ASSETS: Final[str] = "0x01e1d114"  # totalAssets()
SELECTOR_TOTAL_SUPPLY: Final[str] = "0x18160ddd"  # totalSupply()
SELECTOR_CONVERT: Final[str] = "0x07a2d13a"  # convertToAssets(uint256)
SELECTOR_SYMBOL: Final[str] = "0x95d89b41"  # symbol()

_ONE_SHARE: Final[int] = 10**18

#: `convertToAssets(1e18)` for a vault that has never traded. Every vault starts
#: here exactly, by construction: `_decimalsOffset` gives 18-decimal shares over
#: a 6-decimal asset, so one whole share is worth 1.000000 of the base asset at
#: inception.
_INCEPTION_PRICE: Final[int] = 10**6

#: Peers below this are noise — a vault someone deployed and never funded says
#: nothing about strategy, and there are dozens of them on any active fork.
MIN_PEER_ASSETS: Final[float] = 100.0  # in base-asset units

#: Ceiling on peers reported, largest first. A prompt listing forty vaults is
#: not more informative than one listing the eight that hold real money.
MAX_PEERS: Final[int] = 8

#: Peer results are an observation about a small sample over a short window.
#: Lower than a market fact and deliberately so.
PEER_CONFIDENCE: Final[float] = 0.6

#: A peer's `symbol()` is the **most attacker-controlled string in this whole
#: lane** — genesis takes a vault's name as free text, so this is not a name we
#: are trusting, it is a name a stranger chose knowing an LLM would read it.
#: It is bounded and reported by `FactBuilder.subject`, and the label is built
#: address-first so a cap can only ever truncate the name, never the address.


class PeerVaultSource(BaseSource):
    """How the other vaults on this deployment are doing."""

    key = "peers"
    provides = ("yield", "tvl", "volatility")
    description = (
        "Results from the other curated vaults on this deployment, read on-chain from the "
        "factory: return since inception, drawdown and size. Outcomes only — never a peer's "
        "current holdings, so it informs judgement without enabling tick-by-tick mirroring."
    )

    def __init__(
        self,
        settings: Settings,
        *,
        rpc: RpcClient | None = None,
        factory: str | None = None,
        exclude: str | None = None,
        performance_dir: Path | None = None,
    ):
        super().__init__()
        self.settings = settings
        self._rpc = rpc
        self._owns_rpc = rpc is None
        self._factory = factory
        #: The vault being curated. A vault comparing itself to itself learns
        #: nothing and looks foolish doing it.
        self._exclude = (exclude or "").lower()
        self._performance_dir = performance_dir

    @property
    def rpc(self) -> RpcClient:
        if self._rpc is None:
            if not self.settings.rpc_url:
                raise RuntimeError(
                    "no RPC endpoint configured - set DATA_RPC_URL, ANVIL_RPC_URL or "
                    "BASE_RPC_URL so peer vaults can be read on-chain"
                )
            self._rpc = RpcClient(
                self.settings.rpc_url, timeout_s=self.settings.request_timeout_s
            )
        return self._rpc

    # ── the main event ────────────────────────────────────────────────────

    async def fetch(self, assets: list[str]) -> list[Fact]:
        del assets  # a peer's results are not per-asset

        factory = self._factory or _factory_from_manifest()
        if factory is None:
            self.remark(
                "no VaultFactory address available, so there are no peers to compare "
                "against; deploy first or set the factory explicitly"
            )
            return []

        try:
            peers = await self._peer_addresses(factory)
        except RpcError as exc:
            raise RuntimeError(f"could not read the factory's vault list: {exc}") from exc

        scored: list[tuple[float, str, dict]] = []
        for address in peers:
            if address.lower() == self._exclude:
                continue
            try:
                reading = await self._read_peer(address)
            except Exception as exc:  # noqa: BLE001 - one bad peer must not sink the source
                # Deliberately broader than RpcError. A vault the factory
                # created but that does not answer the ERC-4626 surface — a
                # half-deployed clone, or a future contract with a different
                # ABI — raises something else entirely, and losing every peer
                # because one of forty is odd would be the wrong trade.
                logger.debug("skipping peer %s: %s", address, exc)
                continue
            if reading is None:
                continue
            scored.append((reading["assets"], address, reading))

        if not scored:
            self.remark(
                "no other vault on this deployment has a track record to compare against "
                "yet - peers must be funded and must have actually traded"
            )
            return []

        scored.sort(reverse=True, key=lambda row: row[0])
        kept = scored[:MAX_PEERS]
        if len(scored) > MAX_PEERS:
            self.remark(
                f"{len(scored)} funded peers exist; showing the {MAX_PEERS} largest by assets"
            )

        builder = FactBuilder(self.key, chain=self.settings.chain, on_finding=self.diagnose)
        facts: list[Fact] = []
        for _, address, reading in kept:
            facts.extend(self._facts_for(address, reading, builder))
        return facts

    async def _peer_addresses(self, factory: str) -> list[str]:
        """`vaults()` returns `address[]`: offset word, length word, addresses."""
        raw = await self.rpc.call(factory, SELECTOR_VAULTS)
        if len(raw) < 64:
            return []
        count = int.from_bytes(raw[32:64], "big")
        return [
            "0x" + raw[64 + i * 32 + 12 : 64 + (i + 1) * 32].hex()
            for i in range(count)
            if len(raw) >= 64 + (i + 1) * 32
        ]

    async def _read_peer(self, address: str) -> dict | None:
        """Current worth and share price, or None if the vault is unfunded.

        Skipping the unfunded is not tidiness. A fork accumulates dozens of
        empty vaults from genesis experiments, and each one would otherwise
        arrive in the prompt as a peer with a 0% return — which reads as a rival
        that is flat, not as one that never started.
        """
        total_assets = decode_word(await self.rpc.call(address, SELECTOR_TOTAL_ASSETS), 0)
        total_supply = decode_word(await self.rpc.call(address, SELECTOR_TOTAL_SUPPLY), 0)
        if total_supply == 0:
            return None

        # Base-asset decimals are not readable from here without another call
        # per peer; 6 is right for every USDC vault on this deployment and the
        # figure is only used for a floor and for ordering, never displayed raw.
        scaled = total_assets / 10**6
        if scaled < MIN_PEER_ASSETS:
            return None

        argument = hex(_ONE_SHARE)[2:].rjust(64, "0")
        share_price = decode_word(
            await self.rpc.call(address, SELECTOR_CONVERT + argument), 0
        )

        # A vault still sitting at exactly its inception price has never traded,
        # so it has no track record to compare against. Found on the first live
        # run: seven of the eight "peers" reported were e2e test vaults holding
        # exactly 1,000 USDC at exactly 0.000% — identical, uninformative, and
        # they buried the one real rival. A peer with no history is not a rival,
        # it is a deployment artifact.
        if share_price == _INCEPTION_PRICE:
            return None

        # A label, not data. A vault that does not implement `symbol()` is still
        # a peer worth reporting, so this degrades rather than raising.
        symbol = "vault"
        try:
            symbol = decode_string(await self.rpc.call(address, SELECTOR_SYMBOL)) or "vault"
        except Exception as exc:  # noqa: BLE001 - a missing name is not a missing peer
            logger.debug("peer %s has no readable symbol: %s", address, exc)

        return {"assets": scaled, "share_price": share_price, "symbol": symbol}

    def _facts_for(self, address: str, reading: dict, builder: FactBuilder) -> list[Fact]:
        # ADDRESS FIRST, and the ordering is the whole defence. This label was
        # `"{symbol} {address}"`, which put the one attacker-chosen part of it
        # in front of the one trustworthy part - so a peer naming itself with
        # 60 characters of anything pushed the address past the 64-character
        # cap and off the end. The address is what lets a human check the vault
        # on a block explorer; losing it to a long name is losing the only
        # identity the peer did not choose for itself.
        #
        # Reversed, truncation can only ever eat the attacker's half, and no
        # second cap is needed here - `builder.subject` is the one chokepoint,
        # and it reports what it cleaned. A pre-clean at this call site would
        # have to remember to report, and the first version of it did not.
        label = f"{address[:10]} {reading['symbol']}"
        subject = builder.subject(protocol="curated-vault", market=label)

        facts = [
            builder.usd("tvl", subject, reading["assets"], confidence=PEER_CONFIDENCE)
        ]

        # Return since inception, from the share price. A vault starts at
        # exactly 1.0 by construction (`_decimalsOffset` gives 18-decimal shares
        # over a 6-decimal asset), so the deviation from 1e6 IS the return —
        # no history needed, which is what makes this cheap enough to do
        # per-peer inside one tick.
        if reading["share_price"] > 0:
            since_inception = reading["share_price"] / 10**6 - 1.0
            facts.append(
                builder.apy_from_fraction(
                    subject, since_inception, confidence=PEER_CONFIDENCE
                )
            )

        drawdown = self._drawdown(address)
        if drawdown is not None:
            facts.append(
                builder.ratio(
                    "volatility", subject, drawdown, confidence=PEER_CONFIDENCE
                )
            )
        return facts

    def _drawdown(self, address: str) -> float | None:
        """Worst peak-to-trough fall from the peer's recorded series, if any.

        Read straight off `PerformanceStore`'s JSONL rather than through the
        agent package: this lane must not import the harness, and the file
        format is one JSON object per line with a `share_price` field. A missing
        or unreadable file means no drawdown fact, which is correct — a peer we
        have not been watching has no measured drawdown, and inventing 0% would
        make it look like the safest vault on the deployment.
        """
        if self._performance_dir is None:
            return None
        path = Path(self._performance_dir) / f"{address.lower()}.jsonl"
        if not path.is_file():
            return None

        prices: list[float] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                value = json.loads(line).get("share_price")
                if value is not None:
                    prices.append(float(value))
        except (OSError, ValueError) as exc:
            logger.debug("unreadable peer series for %s: %s", address, exc)
            return None

        if len(prices) < 2:
            return None
        peak, worst = prices[0], 0.0
        for price in prices:
            peak = max(peak, price)
            if peak > 0:
                worst = max(worst, (peak - price) / peak)
        return worst

    async def close(self) -> None:
        if self._rpc is not None and self._owns_rpc:
            await self._rpc.aclose()


def _factory_from_manifest() -> str | None:
    """`VaultFactory` from the deployment manifest Lane A publishes."""
    path = Path("deployments/base-fork.json")
    if not path.is_file():
        return None
    try:
        return (json.loads(path.read_text(encoding="utf-8")).get("contracts") or {}).get(
            "VaultFactory"
        )
    except (OSError, ValueError):
        return None


def make_peer_source(settings: Settings) -> PeerVaultSource:
    """Registration factory. Referenced from `sources/__init__.py`.

    The performance directory is wired from the agent's state dir when present,
    so drawdown facts appear for peers the harness has been recording. Absent,
    the source still reports return and size from the chain alone.
    """
    import os

    state_dir = os.environ.get("AGENT_STATE_DIR")
    performance = Path(state_dir) / "performance" if state_dir else Path(".agent-state/performance")
    return PeerVaultSource(settings, performance_dir=performance)


__all__ = ["PeerVaultSource", "make_peer_source", "MAX_PEERS", "MIN_PEER_ASSETS"]
