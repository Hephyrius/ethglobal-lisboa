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


def test_the_api_value_is_convert_to_assets_scaled_by_ten_to_the_twelve():
    """Request #50: the frozen interface disagrees with itself about this field.

    `vault-state.schema.json` describes it as `convertToAssets(1e18)` — 6-decimal
    for a USDC vault — while `fixtures/vault-state.json` carries the
    dimensionless ratio × 1e18. This API follows the fixture, and Lane A asked
    only that the two agree, so what is pinned here is the **transform between
    them**: anyone cross-checking the API against the chain divides by 10¹².

    Note it is not a clean multiple in the other direction. The chain value is
    this one truncated, which is the practical argument for keeping the
    precision: at 6 decimals a USDC vault's share price cannot move until it has
    gained 0.0001%, so early performance renders as a flat line.
    """
    total_assets, total_supply = 50_000_000000, 49_875 * 10**18
    api = _share_price(total_assets, total_supply, 6, 18)
    on_chain = 10**18 * total_assets // total_supply  # convertToAssets(1e18)

    assert api is not None
    assert on_chain == 1_002_506
    assert int(api) // 10**12 == on_chain


def test_the_fork_vaults_share_price_reconciles_with_request_27():
    """#27 reported the fork vault at `999952` where #11 had said `1e18`, and
    both were right in their own units. 2,499.88 USDC over 2,500 shares."""
    api = _share_price(2_499_880000, 2_500 * 10**18, 6, 18)

    assert api == "999952000000000000"
    assert int(api) // 10**12 == 999_952


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


# ── plan -> executeBatch encoding ─────────────────────────────────────────
#
# ABI encoding and decoding are local operations, so this needs no chain: the
# client is pointed at an unreachable RPC on purpose. What it pins is the seam
# between Lane D's calldata and Lane A's contract — a plan must arrive on-chain
# byte-identical to the one the agent approved and the feed displayed.


@pytest.fixture(scope="module")
def client():
    from agent.chain.vault_client import Web3VaultClient
    from agent.config import Settings

    return Web3VaultClient(
        Settings(
            rpc_url="http://127.0.0.1:1",  # never contacted
            agent_private_key="0x" + "11" * 32,
        )
    )


VAULT = "0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1"


def _encode(client, plan):
    calls = [
        (
            client._w3.to_checksum_address(step.target),
            int(step.value),
            bytes.fromhex(step.calldata.removeprefix("0x")),
        )
        for step in plan.steps
    ]
    return client._vault(VAULT).functions.executeBatch(calls)._encode_transaction_data()


def _decode(client, data):
    """web3 v7 decodes tuple components as dicts; older versions gave tuples."""
    calls = client._vault(VAULT).decode_function_input(data)[1]["calls"]
    out = []
    for entry in calls:
        target, value, payload = (
            (entry["target"], entry["value"], entry["data"])
            if isinstance(entry, dict)
            else (entry[0], entry[1], entry[2])
        )
        raw = payload.hex() if isinstance(payload, bytes | bytearray) else str(payload)
        out.append((target.lower(), int(value), raw.removeprefix("0x").lower()))
    return out


def test_a_plan_survives_encoding_to_executebatch_unchanged(client):
    """Every step's target, value and calldata must round-trip exactly.

    A silent corruption here would send the vault calldata nobody authored,
    against a plan the decision feed is simultaneously showing as correct.
    """
    from agent import fixtures

    plan = fixtures.execution_plan()
    decoded = _decode(client, _encode(client, plan))

    expected = [
        (step.target.lower(), int(step.value), step.calldata.removeprefix("0x").lower())
        for step in plan.steps
    ]
    assert decoded == expected


def test_the_whole_plan_goes_out_as_one_call(client):
    """Atomicity is the reason executeBatch was chosen over N executes: a plan
    lands complete or not at all, never half-applied."""
    from agent import fixtures

    data = _encode(client, fixtures.execution_plan())
    assert data.startswith("0x34fcd5be"), "expected the executeBatch selector"
    assert len(_decode(client, data)) == len(fixtures.execution_plan().steps)


def test_step_order_is_preserved(client):
    """Approvals must precede the calls that need them."""
    from agent import fixtures

    plan = fixtures.execution_plan()
    decoded = _decode(client, _encode(client, plan))
    assert [t for t, _, _ in decoded] == [s.target.lower() for s in plan.steps]


def test_a_live_mode_client_without_a_key_is_refused():
    """The agent signs its own transactions — that is the trust model, so a
    missing key is a configuration error, not a silent read-only mode."""
    from agent.chain.vault_client import Web3VaultClient
    from agent.config import Settings

    with pytest.raises(ValueError, match="AGENT_PRIVATE_KEY"):
        Web3VaultClient(Settings(agent_private_key=None))
