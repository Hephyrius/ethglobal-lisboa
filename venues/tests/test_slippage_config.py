"""The slippage bound travels from the environment into the quote request.

Cross-lane requests 26 and 32: both ends of this existed and nothing connected
them, so the Uniswap API applied its own 250 bps default and the harness
rejected every plan against the golden mandate's 50 bps ceiling. These tests pin
the connection, because the symptom — an agent that reasons correctly and then
refuses to trade — looks like a model problem rather than a config one.
"""

from __future__ import annotations

import pytest

from venues import config as venue_config
from venues.config import VenueConfig
from venues.registry import get_venue
from venues.uniswap.client import QuoteRequest
from venues.uniswap.plan import price_impact_bps, slippage_bps
from venues.uniswap.venue import UniswapVenue


@pytest.fixture
def no_dotenv(monkeypatch):
    """Stop the developer's own `.env` from reaching these tests.

    `VenueConfig.from_env` loads the repo-root `.env`, so a machine that has
    `UNISWAP_SLIPPAGE_BPS` set — which every demo machine now does — would make
    the 'absent' cases unprovable. These tests are about the code path, not
    about local configuration.
    """
    monkeypatch.setattr(venue_config, "load_env", lambda: None)
    monkeypatch.delenv("UNISWAP_SLIPPAGE_BPS", raising=False)


class TestConfigReadsTheBound:
    def test_reads_uniswap_slippage_bps(self, monkeypatch):
        monkeypatch.setenv("UNISWAP_SLIPPAGE_BPS", "50")
        assert VenueConfig.from_env().uniswap_slippage_bps == 50

    def test_absent_means_none_so_the_api_picks(self, no_dotenv):
        assert VenueConfig.from_env().uniswap_slippage_bps is None

    def test_blank_is_treated_as_absent(self, monkeypatch):
        # A key left empty in .env is the common case and must not crash.
        monkeypatch.setenv("UNISWAP_SLIPPAGE_BPS", "   ")
        assert VenueConfig.from_env().uniswap_slippage_bps is None

    @pytest.mark.parametrize("bad", ["abc", "1.5", "-1", "10001"])
    def test_a_nonsense_value_fails_loudly(self, monkeypatch, bad):
        """Silently ignoring a typo'd bound would leave the API default in
        place — the exact failure this whole change exists to remove."""
        monkeypatch.setenv("UNISWAP_SLIPPAGE_BPS", bad)
        with pytest.raises(ValueError, match="UNISWAP_SLIPPAGE_BPS"):
            VenueConfig.from_env()


class TestRegistryWiresItThrough:
    def test_get_venue_passes_the_bound_to_the_adapter(self, monkeypatch):
        monkeypatch.setenv("UNISWAP_SLIPPAGE_BPS", "50")
        venue = get_venue("uniswap", cached=False)
        assert venue._default_slippage_bps == 50

    def test_without_the_env_var_the_adapter_leaves_it_to_the_api(self, no_dotenv):
        venue = get_venue("uniswap", cached=False)
        assert venue._default_slippage_bps is None


class TestQuoteRequestCarriesIt:
    def test_bps_become_the_api_percent_unit(self):
        # The API speaks percent; the mandate speaks basis points. 50 -> 0.5.
        payload = QuoteRequest(
            token_in="0x" + "11" * 20,
            token_out="0x" + "22" * 20,
            amount=1_000_000,
            swapper="0x" + "33" * 20,
            slippage_bps=50,
        ).to_payload()
        assert payload["slippageTolerance"] == 0.5

    def test_absent_bound_omits_the_field_entirely(self):
        payload = QuoteRequest(
            token_in="0x" + "11" * 20,
            token_out="0x" + "22" * 20,
            amount=1_000_000,
            swapper="0x" + "33" * 20,
        ).to_payload()
        # Sending an explicit null would be a validation error, not a default.
        assert "slippageTolerance" not in payload

    def test_the_adapter_uses_its_configured_bound(self, monkeypatch):
        monkeypatch.setenv("UNISWAP_SLIPPAGE_BPS", "50")
        venue = UniswapVenue(config=VenueConfig.from_env(), default_slippage_bps=50)
        assert venue._default_slippage_bps == 50


class TestToleranceVersusImpact:
    """Two different numbers that are easy to conflate, and the harness only
    checks one of them against the mandate."""

    def test_tolerance_is_the_bound_the_harness_checks(self, quote_response):
        assert slippage_bps(quote_response["quote"]) == 250  # recorded default

    def test_impact_is_the_estimate_and_is_much_smaller(self, quote_response):
        impact = price_impact_bps(quote_response["quote"])
        assert impact is not None
        assert impact < slippage_bps(quote_response["quote"])

    def test_missing_impact_is_none_not_zero(self):
        # Zero would read as "no impact" and wrongly flatter the trade.
        assert price_impact_bps({}) is None

    def test_the_effect_string_reports_the_impact_for_the_feed(
        self, quote_response, swap_response
    ):
        from venues.uniswap.plan import build_plan

        plan = build_plan(quote_response, swap_response)
        assert "bps price impact" in (plan.expected_effect or "")


@pytest.mark.live
class TestAgainstTheRealAPI:
    """The whole point of the change: a plan that the golden mandate accepts."""

    GOLDEN_MANDATE_CEILING = 50

    async def test_the_api_honours_the_requested_bound(self, requires_uniswap_key):
        from venues import addresses
        from venues.uniswap.client import UniswapClient

        async with UniswapClient.from_config() as client:
            response = await client.quote(
                QuoteRequest(
                    token_in=addresses.USDC,
                    token_out=addresses.WETH,
                    amount=1_000_000_000,  # 1,000 USDC
                    swapper="0x0000000000000000000000000000000000000001",
                    slippage_bps=self.GOLDEN_MANDATE_CEILING,
                )
            )

        assert slippage_bps(response["quote"]) == self.GOLDEN_MANDATE_CEILING

    async def test_a_real_plan_passes_the_golden_mandate_ceiling(
        self, requires_uniswap_key, monkeypatch
    ):
        """Regression guard for requests 26 and 32. Before the fix this plan
        came back at 250 bps and the harness rejected it — an agent that
        reasoned correctly and then refused to trade, which reads as a model
        failure rather than a missing environment variable."""
        from curator_schema.models import Holding, SwapIntent, VaultState

        from venues import addresses, registry

        monkeypatch.setenv("UNISWAP_SLIPPAGE_BPS", str(self.GOLDEN_MANDATE_CEILING))
        vault = VaultState(
            address="0x0000000000000000000000000000000000000001",
            asset=addresses.USDC,
            asset_decimals=6,
            total_assets="10000000000",
            total_supply="10000000000",
            holdings=[
                Holding(
                    token=addresses.USDC,
                    symbol="USDC",
                    balance="10000000000",
                    decimals=6,
                )
            ],
        )

        venue = registry.get_venue("uniswap", cached=False)
        try:
            plan = await venue.plan(
                SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.10), vault
            )
        finally:
            await venue.aclose()

        assert plan.expected_slippage_bps is not None
        assert plan.expected_slippage_bps <= self.GOLDEN_MANDATE_CEILING, (
            f"plan reports {plan.expected_slippage_bps} bps against a "
            f"{self.GOLDEN_MANDATE_CEILING} bps mandate — the harness will reject it"
        )
