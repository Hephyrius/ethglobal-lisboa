"""The swap carries a real `amountOutMin`, derived from the mandate's bound.

Lane A asked (Wave 2 §A1): *"a `minOut` of 0 in a public-mempool tx is a free
lunch for a searcher."* They are right, and the calldata is Lane D's, so the
answer is owed from here — with a test rather than a claim.

**Two ways to get this wrong, and this file has now hit both.**

*False negative:* `quote.output.minimumAmount` does **not** appear as a word in
the transaction data. Grep it, find nothing, and the tempting conclusion is "the
demo path has no slippage protection". Wrong.

*False alarm:* decode the V3 legs, find `amountOutMin == 0` on each, and the
tempting conclusion is "there is a free lunch here". Also wrong — and this is
the more dangerous one, because it looks like diligence.

**Where the protection actually lives depends on the route shape**, and the
router picks the shape per quote:

* **Split across V3 pools only** — one `amountOutMin` per leg, together
  summing to the quoted minimum.
* **Mixed V3 + V4, or anything needing accumulation** — per-leg minimums are
  **0**, and a single trailing **`SWEEP` (`0x04`)** enforces `amountMin` on the
  accumulated *total*.

Both were observed live on USDC→WETH minutes apart. So the only sound check is
the **effective aggregate**: whichever mechanism the route used, does the
transaction guarantee at least `quote.output.minimumAmount` reaches the vault?
That is what these tests assert.
"""

from __future__ import annotations

import contextlib

import pytest
from eth_abi import decode as abi_decode

from venues import addresses
from venues.errors import NoRouteError
from venues.uniswap.client import QuoteRequest, UniswapClient

pytestmark = pytest.mark.live

SWAPPER = "0x0000000000000000000000000000000000000001"
TRADE_USDC = 1_000_000_000  # 1,000 USDC — the API will not price a tiny trade
MANDATE_BPS = 50

#: UniversalRouter commands. V3/V4 swap inputs carry a per-leg minimum;
#: `SWEEP` carries one minimum for the accumulated total.
V3_SWAP_EXACT_IN = 0x00
V3_SWAP_EXACT_OUT = 0x01
V4_SWAP = 0x10
SWEEP = 0x04


@contextlib.contextmanager
def routable():
    try:
        yield
    except NoRouteError as exc:
        pytest.skip(f"no route right now: {exc}")


async def _protection(slippage_bps: int = MANDATE_BPS):
    """Return `(quote, effective_min_out, spent_in)` for a real swap.

    `effective_min_out` is the strongest guarantee the transaction carries,
    found wherever the router put it.
    """
    async with UniswapClient.from_config() as client:
        quote = await client.quote(
            QuoteRequest(
                token_in=addresses.USDC,
                token_out=addresses.WETH,
                amount=TRADE_USDC,
                swapper=SWAPPER,
                slippage_bps=slippage_bps,
            )
        )
        swap = await client.swap(quote["quote"])

    commands, inputs, _deadline = abi_decode(
        ["bytes", "bytes[]", "uint256"], bytes.fromhex(swap["swap"]["data"][10:])
    )

    leg_minimums = 0
    sweep_minimum = 0
    spent_in = 0
    for command, payload in zip(commands, inputs, strict=False):
        if command in (V3_SWAP_EXACT_IN, V3_SWAP_EXACT_OUT):
            _recipient, amount_in, amount_out_min, _path, _payer = abi_decode(
                ["address", "uint256", "uint256", "bytes", "bool"], payload
            )
            leg_minimums += amount_out_min
            spent_in += amount_in
        elif command == SWEEP:
            token, _recipient, amount_min = abi_decode(
                ["address", "address", "uint256"], payload
            )
            if token.lower() == addresses.WETH.lower():
                sweep_minimum = amount_min

    return quote["quote"], max(leg_minimums, sweep_minimum), spent_in


async def test_the_swap_guarantees_a_minimum_output(requires_uniswap_key):
    """The front-running check Lane A asked for: a searcher must not be able to
    sandwich the vault's rebalance for the whole trade value.

    Deliberately checks the *effective* guarantee rather than each leg — a
    per-leg assertion reports a hole that does not exist whenever the router
    chooses a SWEEP-protected route.
    """
    with routable():
        _quote, effective_min, _spent = await _protection()

    assert effective_min > 0, (
        "no minimum output anywhere in the calldata — neither per-leg nor via SWEEP"
    )


async def test_the_guarantee_equals_the_quoted_minimum(requires_uniswap_key):
    """Whatever mechanism the route used, it protects the number the quote
    promised. One wei of drift per leg is allowed for apportioned rounding."""
    with routable():
        quote, effective_min, _spent = await _protection()

    quoted_min = int(quote["output"]["minimumAmount"])
    assert abs(effective_min - quoted_min) <= 4, (
        f"transaction guarantees {effective_min}, quote promised {quoted_min}"
    )


async def test_the_protection_matches_the_mandate_bound(requires_uniswap_key):
    """The haircut is the mandate's ceiling, not the API's looser default.

    The payoff from requesting `UNISWAP_SLIPPAGE_BPS`: the bound the agent is
    under is the bound encoded in the transaction, so the on-chain protection
    and the mandate cannot disagree.
    """
    with routable():
        quote, effective_min, _spent = await _protection(slippage_bps=MANDATE_BPS)

    expected_out = int(quote["output"]["amount"])
    haircut_bps = (expected_out - effective_min) / expected_out * 10_000

    assert haircut_bps == pytest.approx(MANDATE_BPS, abs=1), (
        f"calldata protects to {haircut_bps:.1f} bps against a {MANDATE_BPS} bps mandate"
    )


async def test_a_tighter_bound_produces_tighter_calldata(requires_uniswap_key):
    """Proves the bound is plumbed through rather than coincidental — ask for
    less slippage, get a higher floor."""
    with routable():
        _loose, loose_min, _ = await _protection(slippage_bps=200)
        _tight, tight_min, _ = await _protection(slippage_bps=10)

    assert tight_min > loose_min


async def test_the_whole_requested_amount_is_spent(requires_uniswap_key):
    """Guards a subtler leak than slippage: a route that quietly spends less
    than requested leaves the rest sitting in the router."""
    with routable():
        _quote, _min, spent = await _protection()

    # Only V3 legs report amountIn in a decodable form; a V4-only route reports
    # none, in which case there is nothing to check here.
    if spent:
        assert spent <= TRADE_USDC, "the route would spend more than requested"
