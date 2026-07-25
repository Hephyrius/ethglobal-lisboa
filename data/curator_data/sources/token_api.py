"""Graph · Token API — spot prices derived from executed DEX swaps.

Separate from `messari` on purpose, and the separation is the point: this
source knows nothing about subgraphs, speaks REST rather than GraphQL, uses a
*different credential*, and contributes a different `Fact.kind`. Two sources
sharing no code path merging into one snapshot is the registry design working,
demonstrated with providers we actually ship.

## There is no price endpoint on Base — and that is by design

`/networks` reports Base indexed for `balances`, `dexes` and `transfers` only;
there is no `prices` category. Price on this chain is therefore *derived from
executed swaps*, which makes this source mechanically independent of an oracle
— see `sources/chainlink.py` for the oracle view of the same number.

## The orientation trap, and why we do not read the API's `price` field

`/evm/swaps` returns a `price` field, and it **flips with the direction of the
swap**. Verified live on the WETH/USDC pool, consecutive swaps:

    WETH -> USDC   price = 1858.0228     (USDC per WETH)
    USDC -> WETH   price =    0.0005     (WETH per USDC)

Reading `price` off the most recent swap is therefore a coin flip between the
right number and one wrong by a factor of ~3.4 million. Nothing about the
response says which you got.

So the price is **computed from both legs, matched by contract address**:
whichever side is the quote token supplies the numerator, whichever is the
target supplies the denominator. That is orientation-proof by construction. A
**median over several swaps** then resists a single fat-fingered trade — one
$0.08 swap in the sample above priced 0.4% off the rest.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from typing import Any

import httpx
from curator_schema.models import Fact

from ..config import Settings
from ..facts import FactBuilder
from ..http import LoopBoundClient
from ..ports import BaseSource
from .pools import pool_for
from .tokens import address_for, known_symbols

logger = logging.getLogger(__name__)

#: Tokens accepted as the USD leg of a pool. A swap priced against one of these
#: is a USD price to within the peg. Ordered by preference.
QUOTE_TOKENS: tuple[str, ...] = ("USDC", "USDbC", "DAI")

#: Rows per request. **10 is the free plan's hard ceiling** — verified live,
#: `limit=20` returns `403 forbidden: Parameter 'limit' exceeds ...`. Enough to
#: median out one odd trade, and raising it silently breaks every call.
MAX_PAGE = 10

#: Swaps averaged per price.
SWAP_SAMPLE = MAX_PAGE

#: Candidate pools examined when discovering one for a token.
POOL_SAMPLE = MAX_PAGE

#: The Token API's identifier for Base mainnet.
NETWORK_IDS: dict[str, str] = {"base": "base"}


#: Markers that identify a 403 as a plan/parameter complaint rather than a
#: rejected credential. Live text: "Parameter 'limit' exceeds ...".
_QUOTA_MARKERS = ("parameter", "limit", "exceeds", "quota", "plan")

#: Pause before the single retry on a 5xx. Short on purpose — this sits inside
#: the registry's per-source deadline, and a source that spends its whole budget
#: sleeping has traded one failure for a slower one.
_RETRY_BACKOFF_S = 0.4


def _is_quota_complaint(body: str) -> bool:
    lowered = (body or "").lower()
    return any(marker in lowered for marker in _QUOTA_MARKERS)


def _norm(address: str | None) -> str:
    """Addresses come back lowercase; our tables are checksummed."""
    return (address or "").strip().lower()


def _leg(swap: dict, side: str) -> tuple[str, float | None]:
    """(address, token amount) for the input or output side of a swap."""
    token = swap.get(f"{side}_token") or {}
    value = swap.get(f"{side}_value")
    try:
        amount = float(value) if value is not None else None
    except (TypeError, ValueError):
        amount = None
    return _norm(token.get("address")), amount


class TokenApiSource(BaseSource):
    """USD spot prices for permitted assets, derived from executed swaps."""

    key = "token_api"
    provides = ("price",)
    description = (
        "USD spot prices from The Graph's Token API, derived from executed DEX swaps "
        "on Base. Mechanically independent of an oracle, so it cross-validates "
        "Chainlink rather than repeating it."
    )

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ):
        super().__init__()
        self.settings = settings
        self._owns_client = client is None
        self._http = LoopBoundClient(
            lambda: httpx.AsyncClient(timeout=settings.request_timeout_s)
        )
        self._http.adopt(client)
        #: symbol -> (pool address, quote token address). Discovery is one
        #: request, and the answer does not change within a run.
        self._pools: dict[str, tuple[str, str]] = {}

    @property
    def client(self) -> httpx.AsyncClient:
        return self._http.get_client()

    async def fetch(self, assets: list[str]) -> list[Fact]:
        if not self.settings.token_api_key:
            # Whole-source failure: with no credential nothing can be fetched,
            # so this belongs in errors[] as one clear line.
            raise RuntimeError(
                "TOKEN_API_KEY is not set - the Token API needs its own bearer JWT from "
                "The Graph Market. GRAPH_API_KEY is rejected with 401."
            )

        network = NETWORK_IDS.get(self.settings.chain, self.settings.chain)
        builder = FactBuilder(self.key, chain=self.settings.chain)
        quotes = {_norm(address_for(q, self.settings.chain)) for q in QUOTE_TOKENS}
        quotes.discard("")

        facts: list[Fact] = []
        for symbol in dict.fromkeys(a.strip().upper() for a in assets if a and a.strip()):
            address = address_for(symbol, self.settings.chain)
            if address is None:
                self.note(
                    f"no known contract address for {symbol} on {self.settings.chain} "
                    f"(known: {', '.join(known_symbols(self.settings.chain))}) - "
                    f"add it to curator_data/sources/tokens.py"
                )
                continue

            if _norm(address) in quotes:
                # The quote leg cannot be priced against itself. Its price is a
                # peg assumption, and asserting one here would be inventing a
                # number — the Chainlink source carries a real feed for it.
                #
                # `remark`, not `note`: this is a category mistake, not an
                # outage. It fired on 35 of 36 journalled ticks and the prompt
                # showed it to the model as data it could not read, which is
                # how an agent learns to distrust a feed that never broke.
                self.remark(
                    f"{symbol} is the quote token here, so a dex-derived price for it would "
                    f"be a price against itself; the chainlink oracle source carries it instead"
                )
                continue

            price = await self._price(symbol, address, network, quotes)
            if price is not None:
                facts.append(builder.usd("price", builder.subject(token=symbol), price))
        return facts

    # ── price ─────────────────────────────────────────────────────────────

    async def _price(
        self, symbol: str, address: str, network: str, quotes: set[str]
    ) -> float | None:
        pool = await self._pool_for(symbol, address, network, quotes)
        if pool is None:
            return None
        pool_address, quote_address = pool

        swaps = await self._get(
            f"/evm/swaps?network={network}&pool={pool_address}&limit={SWAP_SAMPLE}"
        )
        if swaps is None:
            self.note(f"price for {symbol} unavailable: no swaps returned for pool {pool_address}")
            return None

        target = _norm(address)
        observations: list[float] = []
        for swap in swaps:
            in_addr, in_amount = _leg(swap, "input")
            out_addr, out_amount = _leg(swap, "output")
            legs = {in_addr: in_amount, out_addr: out_amount}
            target_amount = legs.get(target)
            quote_amount = legs.get(quote_address)
            # Orientation-proof: which side the token sat on is irrelevant.
            if target_amount and quote_amount and target_amount > 0:
                observations.append(quote_amount / target_amount)

        if not observations:
            self.note(f"price for {symbol} unavailable: no usable swap legs in the last "
                      f"{SWAP_SAMPLE} trades")
            return None

        price = statistics.median(observations)
        return price if price > 0 else None

    async def _pool_for(
        self, symbol: str, address: str, network: str, quotes: set[str]
    ) -> tuple[str, str] | None:
        """Find the deepest pool pairing `address` with a USD quote token.

        Discovered rather than hard-coded: a pinned pool address is one more
        thing to go stale between now and the demo, and discovery is a single
        request whose answer is cached for the process.
        """
        cached = self._pools.get(symbol)
        if cached is not None:
            return cached

        # A pinned pool skips discovery entirely. That matters twice over:
        # every call against this API costs 8-10s, and `/evm/pools` was
        # observed returning HTTP 500, which would make the source fail for a
        # token we already know the answer for.
        pinned = pool_for(symbol, self.settings.chain)
        if pinned is not None:
            self._pools[symbol] = (pinned[0], _norm(pinned[1]))
            return self._pools[symbol]

        pools = await self._get(
            f"/evm/pools?network={network}&token={address}&limit={POOL_SAMPLE}"
        )
        if pools is None:
            self.note(f"price for {symbol} unavailable: pool discovery returned nothing")
            return None

        target = _norm(address)
        best: tuple[int, str, str] | None = None
        for pool in pools:
            in_addr = _norm((pool.get("input_token") or {}).get("address"))
            out_addr = _norm((pool.get("output_token") or {}).get("address"))
            if target not in (in_addr, out_addr):
                continue
            counterpart = out_addr if target == in_addr else in_addr
            if counterpart not in quotes:
                continue
            # `transactions` is the closest thing to depth the API exposes, and
            # the busiest pool is the one least moved by a single trade.
            activity = int(pool.get("transactions") or 0)
            if best is None or activity > best[0]:
                best = (activity, str(pool.get("pool")), counterpart)

        if best is None:
            self.note(
                f"price for {symbol} unavailable: no pool pairs it with a USD quote token "
                f"({', '.join(QUOTE_TOKENS)}) among the top {POOL_SAMPLE}"
            )
            return None

        resolved = (best[1], best[2])
        self._pools[symbol] = resolved
        return resolved

    # ── transport ─────────────────────────────────────────────────────────

    async def _get(self, path: str) -> list[dict] | None:
        """GET a Token API route, returning its `data` rows or None.

        Retries once on a 5xx or a transport error. Observed live: `/evm/pools`
        and `/evm/swaps` each returned a one-off HTTP 500, and each cost the
        snapshot a price it would have got on a second attempt a moment later.
        Client errors are not retried — a 403 for an over-large page will be a
        403 again, and retrying a rejected credential is how you get rate
        limited for being wrong twice as fast.
        """
        url = self.settings.token_api_url.rstrip("/") + path
        response = None
        for attempt in (1, 2):
            try:
                response = await self.client.get(url, headers=self._headers())
            except httpx.HTTPError as exc:
                if attempt == 1:
                    await asyncio.sleep(_RETRY_BACKOFF_S)
                    continue
                self.note(f"Token API unreachable: {type(exc).__name__}: {exc}")
                return None
            if response.status_code < 500 or attempt == 2:
                break
            await asyncio.sleep(_RETRY_BACKOFF_S)

        if response is None:  # pragma: no cover - defensive; the loop always sets it
            return None

        # A 403 is NOT necessarily a credential problem here: the free plan
        # returns 403 for an over-large `limit` too. Killing the whole source
        # over a page-size mistake would be the same misclassification as
        # treating the subgraph gateway's auth error as a schema error.
        if response.status_code == 403 and _is_quota_complaint(response.text):
            self.note(f"Token API plan limit hit on {path.split('?')[0]}: {response.text[:120]}")
            return None
        if response.status_code in (401, 403):
            # A real credential problem is not per-route; fail the whole source.
            raise RuntimeError(
                f"Token API rejected the credential (HTTP {response.status_code}) - "
                f"TOKEN_API_KEY must be a Graph Market JWT, not GRAPH_API_KEY"
            )
        if response.status_code >= 400:
            self.note(f"Token API returned HTTP {response.status_code} for {path.split('?')[0]}")
            return None

        try:
            body: Any = response.json()
        except ValueError:
            self.note(f"Token API returned non-JSON for {path.split('?')[0]}")
            return None

        rows = body.get("data") if isinstance(body, dict) else None
        return rows if rows else None

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.settings.token_api_key}",
        }

    async def close(self) -> None:
        if self._owns_client:
            await self._http.aclose()


def make_token_api_source(settings: Settings) -> TokenApiSource:
    """Registration factory. Referenced from `sources/__init__.py`."""
    return TokenApiSource(settings)


__all__ = ["TokenApiSource", "make_token_api_source", "QUOTE_TOKENS", "SWAP_SAMPLE"]
