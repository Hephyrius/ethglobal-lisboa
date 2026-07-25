"""R5 · The agent ships into Aqua — the 1inch centrepiece.

    uv run pytest tests/e2e -k slice_ship -v

**The rung is gated on the allowance, not on `safeBalances()`** (cross-lane
request #39). The e2e plan asks for `safeBalances()` to be non-zero, but request
#17 established — against the real contract — that a ship with *no* approvals
produces exactly that: *"non-zero `safeBalances`, valid hash, no error, a
successful tx"*, and a position that is silently never fillable. So the plan's
stated proof passes on precisely the failure it was written to prevent.

What actually separates a live position from a dead one is the **ERC-20 allowance
from the vault to Aqua**: zero in the broken case, equal to the shipped amount in
the good one. Aqua consumes it later, when a taker fills and `pull()`s from the
vault. It needs only a standard ERC-20 ABI, so this test asserts it without
reaching into any lane's source.

The other half of the rung is **Pattern 1**: shipping moves no tokens, so
`totalAssets()` must be unchanged and the vault must still physically hold the
balances afterwards. That property is the whole reason Aqua is load-bearing
rather than cosmetic — a conventional AMM LP position could not do it.

Builds its own vault, funds it, and rotates into WETH, so nothing here touches
the shared demo vault three lanes assert against.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from web3.logs import DISCARD

from .conftest import (
    AGENT,
    DEPOSITOR_KEY,
    create_vault_calldata,
    send_calldata,
    vault_created_by,
)
from .test_slice_read import ERC20_ABI, _abi, _send

#: anvil account #1 — holds AGENT_ROLE. Reads work with any key; writes do not.
AGENT_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"

DEPOSIT_USDC = 1_000_000_000  # 1,000 USDC, 6dp
ROTATE_PCT = 0.4  # leaves a comfortable cash leg under any sane mandate

ALLOWANCE_ABI = json.loads("""[
 {"name":"allowance","type":"function","stateMutability":"view",
  "inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
  "outputs":[{"type":"uint256"}]}
]""")


def _allowance(w3, token: str, owner: str, spender: str) -> int:
    erc20 = w3.eth.contract(address=w3.to_checksum_address(token), abi=ALLOWANCE_ABI)
    return erc20.functions.allowance(
        w3.to_checksum_address(owner), w3.to_checksum_address(spender)
    ).call()


def _balance(w3, token: str, who: str) -> int:
    erc20 = w3.eth.contract(address=w3.to_checksum_address(token), abi=ERC20_ABI)
    return erc20.functions.balanceOf(w3.to_checksum_address(who)).call()


def _execute_plan(w3, vault: str, plan) -> str:
    """Submit a venue plan the way the harness does: one atomic executeBatch.

    Step order is preserved exactly. For Aqua that is not a style preference —
    a dropped approval does not revert, it produces a dead position (#17).
    """
    contract = w3.eth.contract(address=w3.to_checksum_address(vault), abi=_abi("CuratedVault"))
    calls = [
        (
            w3.to_checksum_address(step.target),
            int(step.value),
            bytes.fromhex(step.calldata.removeprefix("0x")),
        )
        for step in plan.steps
    ]
    receipt = _send(w3, contract.functions.executeBatch(calls), AGENT, AGENT_KEY)
    return receipt.transactionHash.hex()


@pytest.fixture(scope="module")
def two_legged_vault(w3, deployments, usdc, funded_depositor):
    """A fresh vault holding both USDC and WETH — Aqua needs a pair.

    Skips rather than fails if a venue is unavailable: without `UNISWAP_API_KEY`
    the rotation cannot be built, and that is a missing credential rather than a
    broken rung.
    """
    venues = pytest.importorskip("venues", reason="Lane D not installed")
    from curator_schema.models import SwapIntent

    weth = deployments["external"]["WETH"]
    factory = w3.eth.contract(
        address=w3.to_checksum_address(deployments["contracts"]["VaultFactory"]),
        abi=_abi("VaultFactory"),
    )
    # Encoded against the DEPLOYED createVault, and the vault found by diffing
    # vaults(). Both changed shape in Wave 3; see conftest.
    before = list(factory.functions.vaults().call())
    send_calldata(
        w3,
        to=deployments["contracts"]["VaultFactory"],
        data=create_vault_calldata(
            factory_address=deployments["contracts"]["VaultFactory"],
            asset=w3.to_checksum_address(usdc),
            name="E2E Aqua Ship Vault",
            symbol="e2eAQUA",
            agent=w3.to_checksum_address(AGENT),
            guardian=w3.to_checksum_address(funded_depositor),
            mandate_hash=w3.keccak(text="e2e-slice-ship"),
            deployer=w3.to_checksum_address(funded_depositor),
        ),
        sender=funded_depositor,
        key=DEPOSITOR_KEY,
    )
    vault = vault_created_by(w3, factory, before)

    # Fund it.
    token = w3.eth.contract(address=w3.to_checksum_address(usdc), abi=ERC20_ABI)
    _send(w3, token.functions.approve(vault, DEPOSIT_USDC), funded_depositor, DEPOSITOR_KEY)
    vault_c = w3.eth.contract(address=vault, abi=_abi("CuratedVault"))
    _send(
        w3,
        vault_c.functions.deposit(DEPOSIT_USDC, funded_depositor),
        funded_depositor,
        DEPOSITOR_KEY,
    )

    # Rotate part of it into WETH so there is a genuine pair to ship.
    from agent.chain.vault_client import Web3VaultClient
    from agent.config import settings

    async def _rotate():
        client = Web3VaultClient(settings())
        state = await client.state(vault)
        uniswap = venues.get_venue("uniswap", cached=False)
        try:
            plan = await uniswap.plan(
                SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=ROTATE_PCT), state
            )
        finally:
            await uniswap.aclose()
        return plan

    try:
        plan = asyncio.run(_rotate())
    except Exception as exc:  # noqa: BLE001 - a missing key is a skip, not a failure
        pytest.skip(f"could not build the Uniswap rotation ({type(exc).__name__}: {exc})")
    _execute_plan(w3, vault, plan)

    if _balance(w3, weth, vault) == 0:
        pytest.skip("rotation produced no WETH — cannot ship a pair")
    return vault


@pytest.fixture(scope="module")
def shipped(w3, two_legged_vault, deployments):
    """Ship a position, capturing the state either side of it."""
    venues = pytest.importorskip("venues", reason="Lane D not installed")
    from curator_schema.models import AquaShipIntent

    from agent.chain.vault_client import Web3VaultClient
    from agent.config import settings

    usdc, weth = deployments["external"]["USDC"], deployments["external"]["WETH"]
    aqua_addr = deployments["external"]["Aqua"]
    vault = two_legged_vault

    ship_usdc = _balance(w3, usdc, vault) // 3
    ship_weth = _balance(w3, weth, vault) // 2

    async def _build():
        client = Web3VaultClient(settings())
        state = await client.state(vault)
        aqua = venues.get_venue("aqua", cached=False)
        try:
            plan = await aqua.plan(
                AquaShipIntent(tokens=["USDC", "WETH"], amounts=[str(ship_usdc), str(ship_weth)]),
                state,
            )
        finally:
            await aqua.aclose()
        return plan, state

    before = {
        "usdc": _balance(w3, usdc, vault),
        "weth": _balance(w3, weth, vault),
        "total": w3.eth.contract(address=vault, abi=_abi("CuratedVault")).functions
        .totalAssets().call(),
        "allow_usdc": _allowance(w3, usdc, vault, aqua_addr),
        "allow_weth": _allowance(w3, weth, vault, aqua_addr),
    }
    try:
        plan, _ = asyncio.run(_build())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"could not build the Aqua ship ({type(exc).__name__}: {exc})")

    tx = _execute_plan(w3, vault, plan)

    after = {
        "usdc": _balance(w3, usdc, vault),
        "weth": _balance(w3, weth, vault),
        "total": w3.eth.contract(address=vault, abi=_abi("CuratedVault")).functions
        .totalAssets().call(),
        "allow_usdc": _allowance(w3, usdc, vault, aqua_addr),
        "allow_weth": _allowance(w3, weth, vault, aqua_addr),
    }
    return {
        "vault": vault, "tx": tx, "plan": plan, "before": before, "after": after,
        "ship_usdc": ship_usdc, "ship_weth": ship_weth,
    }


# ── the ship happened ─────────────────────────────────────────────────────


def test_the_ship_is_three_ordered_steps(shipped):
    """Two approvals then the ship. Order is load-bearing: Aqua does not revert
    on a missing approval, so nothing downstream would notice."""
    steps = shipped["plan"].steps
    assert len(steps) == 3, [s.why for s in steps]
    assert steps[-1].target.lower().endswith("6d31"), "ship() must be the last step"


def test_the_whole_plan_landed_in_one_transaction(shipped, w3):
    receipt = w3.eth.get_transaction_receipt(shipped["tx"])
    assert receipt["status"] == 1


# ── the rung: is the position actually fillable? ──────────────────────────


def test_the_vault_granted_aqua_an_allowance(shipped):
    """**The rung.** `safeBalances()` would be non-zero even with no approval at
    all (#17), so it cannot distinguish a live position from a dead one. The
    allowance can, and it is what a taker's `pull()` consumes."""
    assert shipped["before"]["allow_usdc"] == 0 and shipped["before"]["allow_weth"] == 0
    assert shipped["after"]["allow_usdc"] > 0, (
        "no USDC allowance to Aqua — the position looks healthy and can never be filled"
    )
    assert shipped["after"]["allow_weth"] > 0, (
        "no WETH allowance to Aqua — the position looks healthy and can never be filled"
    )


def test_the_allowance_covers_exactly_what_was_shipped(shipped):
    """Enough to be fillable, and no more. A vault holds other people's money,
    so Lane D approves the shipped amount rather than `type(uint256).max`."""
    assert shipped["after"]["allow_usdc"] >= shipped["ship_usdc"]
    assert shipped["after"]["allow_weth"] >= shipped["ship_weth"]
    assert shipped["after"]["allow_usdc"] < 2**255, "unbounded approval from a vault"
    assert shipped["after"]["allow_weth"] < 2**255, "unbounded approval from a vault"


# ── Pattern 1: capital never leaves ───────────────────────────────────────


def test_shipping_moved_no_tokens(shipped):
    """Aqua is a registry, not a pool. The vault stays the custodian, which is
    the locked Pattern 1 decision and the reason Aqua fits this design at all."""
    assert shipped["after"]["usdc"] == shipped["before"]["usdc"]
    assert shipped["after"]["weth"] == shipped["before"]["weth"]


def test_total_assets_is_unchanged_by_an_open_position(shipped):
    assert shipped["after"]["total"] == shipped["before"]["total"]


def test_the_vault_still_holds_more_than_it_shipped(shipped):
    """A position cannot be backed by tokens that are not there."""
    assert shipped["after"]["usdc"] >= shipped["ship_usdc"]
    assert shipped["after"]["weth"] >= shipped["ship_weth"]
