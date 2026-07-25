"""Live tests against the real Uniswap Trading API.

Skipped automatically without `UNISWAP_API_KEY`, so a fresh clone is still
green. Run explicitly with `uv run pytest venues/tests -m live`.

These exist because the demo path must use live data, and because the offline
fixtures are only trustworthy while the real API still behaves the way they
recorded. When the API changes, this is what tells us — not the demo.
"""

from __future__ import annotations

import pytest
from curator_schema.models import Holding, SwapIntent, VaultState

from venues import addresses
from venues.errors import VenueAPIError
from venues.uniswap.client import QuoteRequest, UniswapClient
from venues.uniswap.plan import build_plan
from venues.uniswap.venue import UniswapVenue

pytestmark = pytest.mark.live

#: A vault that does not exist yet. Quoting does not require a funded account —
#: `swapper` only shapes the calldata's recipient — so the whole path is
#: exercisable before Lane A has deployed anything.
SWAPPER = "0x0000000000000000000000000000000000000001"

ONE_USDC = 1_000_000


def _vault_state(usdc_balance: int = 10_000_000_000) -> VaultState:
    return VaultState(
        address=SWAPPER,
        asset=addresses.USDC,
        total_assets=str(usdc_balance),
        total_supply=str(usdc_balance),
        holdings=[
            Holding(
                token=addresses.USDC,
                symbol="USDC",
                balance=str(usdc_balance),
                decimals=6,
            )
        ],
        asset_decimals=6,
    )


async def test_quote_returns_a_live_route(requires_uniswap_key):
    async with UniswapClient.from_config() as client:
        response = await client.quote(
            QuoteRequest(
                token_in=addresses.USDC,
                token_out=addresses.WETH,
                amount=ONE_USDC,
                swapper=SWAPPER,
            )
        )

    quote = response["quote"]
    assert quote["route"], "no route returned"
    assert int(quote["output"]["amount"]) > 0
    assert quote["input"]["token"].lower() == addresses.USDC.lower()


async def test_full_quote_then_swap_produces_an_executable_plan(requires_uniswap_key):
    """The whole taker path: /quote → /swap → schema-valid ExecutionPlan."""
    async with UniswapClient.from_config() as client:
        quote_response = await client.quote(
            QuoteRequest(
                token_in=addresses.USDC,
                token_out=addresses.WETH,
                amount=ONE_USDC,
                swapper=SWAPPER,
            )
        )
        swap_response = await client.swap(quote_response["quote"])

    plan = build_plan(quote_response, swap_response)

    assert plan.venue == "uniswap"
    assert len(plan.steps) == 3
    assert plan.steps[-1].calldata.startswith("0x3593564c")  # UniversalRouter.execute
    assert plan.expected_slippage_bps is not None
    assert plan.quote_expires_at is not None
    for step in plan.steps:
        assert step.target.lower() in addresses.EXPECTED_ALLOWLIST


async def test_venue_resolves_pct_of_holdings_against_real_vault_state(
    requires_uniswap_key,
):
    """`pct_of_holdings` is the form a model reliably emits. It must resolve
    against the vault's actual balance, never against a model-supplied number."""
    venue = UniswapVenue()
    try:
        plan = await venue.plan(
            SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.01),
            _vault_state(usdc_balance=10_000_000_000),  # 10,000 USDC
        )
    finally:
        await venue.aclose()

    # 1% of 10,000 USDC = 100 USDC = 100_000_000 base units.
    assert "100" in (plan.expected_effect or "")
    assert plan.steps[0].calldata.endswith(hex(100_000_000)[2:].zfill(64))


async def test_routing_preference_classic_is_rejected(requires_uniswap_key):
    """Regression guard for the FEEDBACK.md finding: the documented-looking
    `CLASSIC` value is refused, even though successful responses echo it back
    as `routing: CLASSIC`."""
    request = QuoteRequest(
        token_in=addresses.USDC,
        token_out=addresses.WETH,
        amount=ONE_USDC,
        swapper=SWAPPER,
    )
    payload = request.to_payload() | {"routingPreference": "CLASSIC"}

    async with UniswapClient.from_config() as client:
        with pytest.raises(VenueAPIError) as caught:
            await client._post("/quote", payload)

    assert caught.value.status == 400
    assert "BEST_PRICE" in (caught.value.detail or "")
