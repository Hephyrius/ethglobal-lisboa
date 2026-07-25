"""R2 — the first true vertical slice: chain → agent → API.

Creates a *fresh* vault through the factory, deposits into it, and reads it back through the frozen
HTTP API. Three components in one path, none of them mocked.

Deliberately creates its own vault rather than using the shared demo vault `0x0E2c…B5d1`, which
Lanes B, D and E all assert against. That makes this safe to run repeatedly during a working
session — the failure mode we are avoiding is an integration test that quietly moves the state
everyone else is testing against.

    uv run pytest tests/e2e -k slice_read -v
"""

from __future__ import annotations

import json

import pytest
from curator_schema import VaultState

from .conftest import AGENT, DEPOSITOR_KEY, REPO_ROOT

ABIS = REPO_ROOT / "contracts" / "abis"
DEPOSIT_USDC = 1_000_000_000  # 1,000 USDC, 6dp

# Enough of ERC-20 to approve and read. The vault ABI is Lane A's published artifact; this one is
# standard, so hand-writing it beats vendoring a token ABI nobody owns.
ERC20_ABI = json.loads("""[
 {"name":"approve","type":"function","stateMutability":"nonpayable",
  "inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
  "outputs":[{"type":"bool"}]},
 {"name":"balanceOf","type":"function","stateMutability":"view",
  "inputs":[{"name":"account","type":"address"}],"outputs":[{"type":"uint256"}]}
]""")


def _abi(name: str) -> list:
    path = ABIS / f"{name}.json"
    if not path.exists():
        pytest.skip(f"{path.relative_to(REPO_ROOT)} missing — run contracts/script/export-abis.sh")
    return json.loads(path.read_text(encoding="utf-8"))


def _send(w3, fn, sender: str, key: str):
    tx = fn.build_transaction(
        {"from": sender, "nonce": w3.eth.get_transaction_count(sender), "chainId": w3.eth.chain_id}
    )
    signed = w3.eth.account.sign_transaction(tx, key)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(raw), timeout=120)
    assert receipt.status == 1, f"tx reverted: {receipt.transactionHash.hex()}"
    return receipt


@pytest.fixture(scope="module")
def fresh_vault(w3, deployments, usdc, funded_depositor) -> str:
    """A vault created for this run only, funded with a known deposit."""
    factory = w3.eth.contract(
        address=w3.to_checksum_address(deployments["contracts"]["VaultFactory"]),
        abi=_abi("VaultFactory"),
    )
    mandate_hash = w3.keccak(text="e2e-slice-read")

    receipt = _send(
        w3,
        factory.functions.createVault(
            (
                w3.to_checksum_address(usdc),
                "E2E Slice Vault",
                "e2eUSDC",
                w3.to_checksum_address(AGENT),
                w3.to_checksum_address(funded_depositor),
                mandate_hash,
            )
        ),
        funded_depositor,
        DEPOSITOR_KEY,
    )

    from web3.logs import DISCARD

    # DISCARD: the receipt also carries the clone's own init logs, which this ABI cannot decode.
    created = factory.events.VaultCreated().process_receipt(receipt, errors=DISCARD)
    assert created, "factory emitted no VaultCreated event"
    vault = created[0]["args"]["vault"]

    token = w3.eth.contract(address=w3.to_checksum_address(usdc), abi=ERC20_ABI)
    _send(w3, token.functions.approve(vault, DEPOSIT_USDC), funded_depositor, DEPOSITOR_KEY)

    vault_c = w3.eth.contract(address=vault, abi=_abi("CuratedVault"))
    _send(
        w3,
        vault_c.functions.deposit(DEPOSIT_USDC, funded_depositor),
        funded_depositor,
        DEPOSITOR_KEY,
    )
    return vault


def test_factory_creates_a_real_vault(w3, deployments, fresh_vault):
    """The clone exists on-chain and the factory acknowledges it as one of its own."""
    assert w3.eth.get_code(fresh_vault) not in (b"", b"\x00")

    factory = w3.eth.contract(
        address=w3.to_checksum_address(deployments["contracts"]["VaultFactory"]),
        abi=_abi("VaultFactory"),
    )
    assert factory.functions.isVault(fresh_vault).call()


def test_deposit_is_custodied_by_the_vault(w3, usdc, fresh_vault):
    """Pattern 1: the vault is sole custodian, so the deposit is literally its token balance."""
    token = w3.eth.contract(address=w3.to_checksum_address(usdc), abi=ERC20_ABI)
    assert token.functions.balanceOf(fresh_vault).call() == DEPOSIT_USDC


def test_api_returns_a_schema_valid_vault_state(api, fresh_vault):
    """The frozen contract holds across the seam — this is what Wave 0 froze the schema for."""
    import httpx

    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{api}/vault/{fresh_vault}/state")
    assert response.status_code == 200, response.text

    state = VaultState.model_validate(response.json())
    assert int(state.total_assets) == DEPOSIT_USDC
    assert state.address.lower() == fresh_vault.lower()
    assert state.agent is not None and state.agent.lower() == AGENT.lower()


def test_share_price_uses_the_six_decimal_convention(w3, fresh_vault):
    """Shares are 18-decimal over a 6-decimal asset (`_decimalsOffset() = 12`), so
    `convertToAssets(1e18)` returns a **6-decimal** number: 1000000 means 1.00 USDC per share.

    Pinned because request #27 records the fork vault reporting `999952` where an earlier note
    claimed `1e18` — a 10^12 discrepancy that would read as a serious error if it reached the
    submission text. Asserting the convention here stops the wrong figure being quoted.
    """
    vault = w3.eth.contract(address=fresh_vault, abi=_abi("CuratedVault"))
    price = vault.functions.convertToAssets(10**18).call()
    assert 900_000 <= price <= 1_100_000, (
        f"convertToAssets(1e18) = {price}; expected ~1e6 (6-decimal), not ~1e18"
    )
