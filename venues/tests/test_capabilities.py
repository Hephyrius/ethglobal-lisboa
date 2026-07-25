"""The capability manifest.

The bug this exists to prevent, from Wave 1: genesis offered a hardcoded venue
pair, so the fully-built Aave venue could never be granted in a mandate. Any
list of venues that is written down twice will eventually disagree with itself,
so the tests below mostly check that the manifest and the registry cannot.
"""

from __future__ import annotations

import pytest

from venues import capabilities, capability, manifest
from venues.capabilities import _BUILDERS
from venues.config import VenueConfig
from venues.registry import VENUES


@pytest.fixture
def config() -> VenueConfig:
    return VenueConfig.from_env()


class TestItCannotDisagreeWithTheRegistry:
    """The whole point. A venue that exists but is not described is invisible to
    genesis; a venue described but not registered is offered and then fails."""

    def test_every_registered_venue_has_a_manifest(self):
        assert set(_BUILDERS) == set(VENUES), (
            "registry and capability manifest have diverged — this is exactly how "
            "Aave went missing for a wave"
        )

    def test_capabilities_covers_every_registered_key(self, config):
        assert {c.key for c in capabilities(config)} == set(VENUES)

    def test_an_unregistered_key_raises_rather_than_returning_a_blank(self):
        with pytest.raises(KeyError, match="no capability manifest"):
            capability("polymarket")


class TestUnavailableVenuesAreStillDescribed:
    def test_unavailable_venues_are_included_not_filtered(self, config):
        """Silence is how a venue disappears. "Aave is here but this deployment
        cannot value the aToken" is far more useful to render than nothing."""
        described = capabilities(config)
        assert len(described) == len(VENUES)

    def test_an_unavailable_venue_names_the_fix(self, config):
        for cap in capabilities(config):
            if not cap.available:
                assert cap.unavailable_reason, f"{cap.key} is unavailable and says why not"
                # The reason must be actionable, not a status word.
                assert len(cap.unavailable_reason) > 20

    def test_an_available_venue_carries_no_reason(self, config):
        for cap in capabilities(config):
            if cap.available:
                assert cap.unavailable_reason is None


class TestCustodyIsDescribedCorrectly:
    """The field that stops a reader misjudging `totalAssets()`."""

    def test_aqua_is_virtual_because_tokens_never_leave(self, config):
        cap = capability("aqua", config)
        assert cap.custody == "virtual"
        assert "never leave" in cap.custody_note

    def test_aave_is_a_claim_because_the_underlying_really_moves(self, config):
        cap = capability("aave", config)
        assert cap.custody == "claim"
        # onBehalfOf being the vault is what keeps sole custody true here.
        assert "vault" in cap.custody_note

    def test_uniswap_holds_no_position_at_all(self, config):
        cap = capability("uniswap", config)
        assert cap.custody == "rotational"

    def test_the_three_venues_do_genuinely_different_jobs(self, config):
        roles = {c.key: c.role for c in capabilities(config)}
        assert roles == {"uniswap": "taker", "aqua": "maker", "aave": "lender"}


class TestIntentsMatchWhatTheAdaptersServe:
    """A mandate naming a venue must not produce intents it can only reject."""

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("uniswap", {"swap"}),
            ("aqua", {"ship", "dock"}),
            ("aave", {"supply", "withdraw"}),
        ],
    )
    def test_declared_intents(self, config, key, expected):
        assert set(capability(key, config).intents) == expected

    def test_every_declared_token_resolves(self, config):
        from venues.addresses import resolve_token

        for cap in capabilities(config):
            for symbol in cap.tokens:
                assert resolve_token(symbol).startswith("0x")


class TestManifestIsSerialisable:
    def test_manifest_is_plain_json_types(self, config):
        import json

        payload = manifest(config)
        json.dumps(payload)  # raises if anything is not JSON-native
        assert {row["key"] for row in payload} == set(VENUES)

    def test_every_row_carries_the_fields_the_ui_needs(self, config):
        needed = {
            "key",
            "role",
            "summary",
            "intents",
            "tokens",
            "custody",
            "custody_note",
            "available",
            "unavailable_reason",
            "contracts",
        }
        for row in manifest(config):
            assert needed <= set(row)

    def test_contracts_are_addresses(self, config):
        for cap in capabilities(config):
            for name, address in cap.contracts.items():
                assert address.startswith("0x") and len(address) == 42, name


class TestAvailabilityDoesNotTouchTheNetwork:
    def test_reading_the_manifest_makes_no_calls(self, config, monkeypatch):
        """Genesis and the UI call this on every render. A probe per venue would
        put third-party latency on a page load — `probe()` is the opt-in form."""
        import httpx

        def explode(*_a, **_k):  # pragma: no cover - only runs on regression
            raise AssertionError("capabilities() must not perform network I/O")

        monkeypatch.setattr(httpx.AsyncClient, "post", explode)
        monkeypatch.setattr(httpx.Client, "post", explode, raising=False)
        capabilities(config)

    def test_uniswap_availability_follows_the_credential(self, monkeypatch):
        from venues import config as venue_config

        monkeypatch.setattr(venue_config, "load_env", lambda: None)
        for name in ("UNISWAP_API_KEY", "uniswap_key"):
            monkeypatch.delenv(name, raising=False)

        cap = capability("uniswap", VenueConfig.from_env())
        assert not cap.available
        assert "UNISWAP_API_KEY" in (cap.unavailable_reason or "")
