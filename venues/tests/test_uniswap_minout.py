"""The swap carries a real `amountOutMin`, derived from the mandate's bound.

Lane A asked (Wave 2 §A1): *"a `minOut` of 0 in a public-mempool tx is a free
lunch for a searcher."* They are right, and the calldata is Lane D's, so the
answer is owed from here — with a test rather than a claim.

**Why eyeballing the calldata is not enough.** `quote.output.minimumAmount` does
**not** appear as a word in the transaction data, which looks alarming until you
decode it: the Trading API splits a trade across pools, and each leg carries its
*own* `amountOutMin`. The protection is real; it is just distributed. Searching
for the total and finding nothing would be the wrong conclusion, so this decodes
the UniversalRouter payload properly and checks every leg.
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

#: UniversalRouter command bytes for the two V3 swap forms. Each carries
#: `(recipient, amountIn, amountOutMin, path, payerIsUser)`.
V3_SWAP_EXACT_IN = 0x00
V3_SWAP_EXACT_OUT = 0x01


@contextlib.contextmanager
def routable():
    try:
        yield
    except NoRouteError as exc:
        pytest.skip(f"no route right now: {exc}")


async def _swap_legs(slippage_bps: int = MANDATE_BPS):
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
    legs = [
        abi_decode(["address", "uint256", "uint256", "bytes", "bool"], payload)
        for command, payload in zip(commands, inputs, strict=False)
        if command in (V3_SWAP_EXACT_IN, V3_SWAP_EXACT_OUT)
    ]
    return quote["quote"], legs


async def test_no_swap_leg_has_a_zero_minimum_out(requires_uniswap_key):
    """The front-running check Lane A asked for. A zero here would let a
    searcher sandwich the vault's rebalance for the entire trade value."""
    with routable():
        _quote, legs = await _swap_legs()

    assert legs, "no V3 swap leg found in the router calldata"
    for index, (_recipient, amount_in, amount_out_min, _path, _payer) in enumerate(legs):
        assert amount_out_min > 0, f"leg {index} has amountOutMin == 0 — free lunch"
        assert amount_in > 0


async def test_the_legs_sum_to_the_quoted_minimum(requires_uniswap_key):
    """Each leg protects its own slice; together they protect the whole trade.

    Allowing one wei of drift per leg: the API apportions the total across pools
    and each division rounds independently.
    """
    with routable():
        quote, legs = await _swap_legs()

    total_in = sum(leg[1] for leg in legs)
    total_min = sum(leg[2] for leg in legs)
    quoted_min = int(quote["output"]["minimumAmount"])

    assert total_in == TRADE_USDC, "the legs do not spend exactly the requested amount"
    assert abs(total_min - quoted_min) <= len(legs), (
        f"leg minimums sum to {total_min}, quote says {quoted_min} — more than "
        f"per-leg rounding explains"
    )


async def test_the_protection_matches_the_mandate_bound(requires_uniswap_key):
    """The haircut is the mandate's ceiling, not the API's looser default.

    This is the payoff from requesting `UNISWAP_SLIPPAGE_BPS`: the bound the
    agent is under is the bound encoded in the transaction, so the on-chain
    protection and the mandate cannot disagree.
    """
    with routable():
        quote, legs = await _swap_legs(slippage_bps=MANDATE_BPS)

    expected_out = int(quote["output"]["amount"])
    total_min = sum(leg[2] for leg in legs)
    haircut_bps = (expected_out - total_min) / expected_out * 10_000

    assert haircut_bps == pytest.approx(MANDATE_BPS, abs=1), (
        f"calldata protects to {haircut_bps:.1f} bps against a {MANDATE_BPS} bps mandate"
    )


async def test_a_tighter_bound_produces_tighter_calldata(requires_uniswap_key):
    """Proves the bound is genuinely plumbed through rather than coincidental —
    ask for less slippage, get a higher floor."""
    with routable():
        _loose_quote, loose_legs = await _swap_legs(slippage_bps=200)
        _tight_quote, tight_legs = await _swap_legs(slippage_bps=10)

    assert sum(leg[2] for leg in tight_legs) > sum(leg[2] for leg in loose_legs)


async def test_the_payer_is_the_swapper_not_the_router(requires_uniswap_key):
    """`payerIsUser` true means funds are pulled from the vault via Permit2
    rather than assumed to be sitting in the router — which is what makes the
    two approval steps in the plan necessary."""
    with routable():
        _quote, legs = await _swap_legs()

    assert all(leg[4] is True for leg in legs)
