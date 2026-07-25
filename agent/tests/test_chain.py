"""Chain-value conversion — the two pure functions in the vault client.

Both were written against the ABI and both are the kind of thing that looks
obviously correct until a real contract answers. `to_hex_string` in particular
was added *because* reading Lane A's deployed vault produced a `mandate_hash`
that failed schema validation: `bytes.hex()` returns hex without the `0x`
prefix, and `HexBytes.hex()` has included it in some versions and not others.

`_share_price` is tested because it is the number a depositor reads. Getting the
decimal scaling wrong does not raise — it silently reports a vault at 1000× its
real value.
"""

from __future__ import annotations

import pytest

from agent.chain.vault_client import _share_price, to_hex_string

DIGEST = "d00e91f708cf16c2d6e1448f08fe691e0efb134c0247891ff0a886954dc72fcf"


# ── hex normalization ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        bytes.fromhex(DIGEST),
        bytearray.fromhex(DIGEST),
        DIGEST,
        f"0x{DIGEST}",
        f"0X{DIGEST.upper()}".replace("0X", "0x"),
    ],
)
def test_every_representation_normalizes_to_prefixed_lowercase_hex(value):
    """The frozen schema requires ^0x[a-fA-F0-9]{64}$ — anything else 500s at
    the API boundary."""
    assert to_hex_string(value) == f"0x{DIGEST}"


def test_none_stays_none():
    """An older deployment may not expose mandateHash; that is not an error."""
    assert to_hex_string(None) is None


def test_the_prefix_is_never_doubled():
    assert to_hex_string(f"0x{DIGEST}") == f"0x{DIGEST}"
    assert not to_hex_string(f"0x{DIGEST}").startswith("0x0x")


def test_uppercase_hex_is_lowercased():
    assert to_hex_string(DIGEST.upper()) == f"0x{DIGEST}"


# ── share price ───────────────────────────────────────────────────────────


def test_a_fresh_vault_prices_shares_at_exactly_one():
    """2,500 USDC (6dp) against 2,500 shares (18dp) — the real deployed vault."""
    assert _share_price(2_500_000000, 2_500 * 10**18, 6, 18) == str(10**18)


def test_share_price_matches_the_golden_fixture():
    """The fixture states 50,000 USDC over 49,875 shares as 1.002506…e18.

    If this drifts, the dApp and the fixtures disagree about what share price
    even means — and a depositor sees the difference before we do.
    """
    assert _share_price(50_000_000000, 49_875 * 10**18, 6, 18) == "1002506265664160401"


def test_an_empty_vault_has_no_share_price():
    """Division by zero is not a price of zero — the field is omitted."""
    assert _share_price(0, 0, 6, 18) is None


def test_gains_raise_the_share_price_above_one():
    price = _share_price(3_000_000000, 2_500 * 10**18, 6, 18)
    assert price is not None and int(price) > 10**18


def test_losses_lower_it_below_one():
    price = _share_price(2_000_000000, 2_500 * 10**18, 6, 18)
    assert price is not None and int(price) < 10**18


def test_an_eighteen_decimal_base_asset_still_prices_at_one():
    """Not every vault is USDC-denominated; the scaling must not assume 6dp."""
    assert _share_price(10 * 10**18, 10 * 10**18, 18, 18) == str(10**18)


def test_the_result_is_an_integer_string_not_a_float():
    """uint256 crosses the boundary as a decimal string — never a JSON number."""
    price = _share_price(2_500_000000, 2_500 * 10**18, 6, 18)
    assert isinstance(price, str) and price.isdigit()
