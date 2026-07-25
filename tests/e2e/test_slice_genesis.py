"""R6 · Genesis closes the loop — chat to mandate to a real vault on-chain.

The rung's actual question is not "did a vault appear" but **"can a depositor
verify that the mandate they were shown is the one the vault was deployed
against?"** That is a single equality:

    keccak(canonical mandate)  ==  vault.mandateHash()

It is the only verification handle a depositor has — the mandate itself lives
off-chain and is mutable by the agent, so the hash recorded at genesis is what
anchors it. Worth asserting rather than assuming.

Every run deploys a **fresh** vault through the factory, so nothing here touches
the shared demo vault that Lanes B, D and E assert against.

Written by Lane B, which owns `POST /genesis/finalize`; conventions follow
`conftest.py` — public surfaces only, skip rather than fail when the stack is
down.
"""

from __future__ import annotations

import re

import httpx
import pytest
from curator_schema import Mandate

pytestmark = pytest.mark.usefixtures("api")

#: Deliberately not the golden fixture. The golden mandate's 50 bps ceiling is
#: correct for the demo narrative but this rung is about deployment, not trading,
#: and a mandate that cannot trade would make a later failure ambiguous.
GENESIS_MANDATE = {
    "version": 1,
    "name": "R6 Genesis Check",
    "objective": (
        "Hold a balanced book of USDC and WETH on Base, rotating through Uniswap when the "
        "split drifts more than five percentage points from the target."
    ),
    "base_asset": "USDC",
    "constraints": {
        "allowed_assets": ["USDC", "WETH"],
        "max_slippage_bps": 300,
        "max_position_pct": 0.6,
        "min_cash_pct": 0.3,
        "rebalance_cooldown_seconds": 0,
        "max_actions_per_tick": 1,
    },
    "permitted_data_sources": ["messari", "aave", "token_api"],
    "permitted_venues": ["uniswap", "aqua"],
    "risk_posture": "balanced",
}


@pytest.fixture(scope="module")
def genesis(api: str) -> dict:
    """Deploy a fresh vault through the real factory."""
    with httpx.Client(timeout=120.0) as client:
        response = client.post(f"{api}/genesis/finalize", json={"mandate": GENESIS_MANDATE})
    if response.status_code == 503:
        pytest.skip(f"genesis not configured: {response.json().get('detail')}")
    assert response.status_code == 200, response.text
    return response.json()


def test_finalize_returns_a_deployed_vault(genesis: dict):
    assert re.fullmatch(r"0x[a-fA-F0-9]{40}", genesis["vault"])
    assert re.fullmatch(r"0x[a-fA-F0-9]{64}", genesis["deploy_tx"])
    assert re.fullmatch(r"0x[a-fA-F0-9]{64}", genesis["mandate_hash"])


def test_the_deploy_transaction_actually_succeeded(genesis: dict, w3):
    """A hash is not a deployment. Check the receipt."""
    receipt = w3.eth.get_transaction_receipt(genesis["deploy_tx"])
    assert receipt["status"] == 1, "createVault reverted"


def test_the_vault_has_bytecode(genesis: dict, w3):
    """Guards against the stub client, which returns a plausible address that is
    not a contract. That fallback is silent by design, so this is the assertion
    that distinguishes a real deployment from it."""
    assert w3.eth.get_code(w3.to_checksum_address(genesis["vault"])) not in (b"", b"\x00")


def test_the_onchain_hash_equals_the_hash_the_user_was_shown(genesis: dict, api: str):
    """**The rung.** This equality is the depositor's whole verification story."""
    with httpx.Client(timeout=30.0) as client:
        state = client.get(f"{api}/vault/{genesis['vault']}/state").json()

    assert state["mandate_hash"] == genesis["mandate_hash"], (
        "the vault was deployed against a different mandate than the one shown at genesis — "
        "a depositor could not verify anything"
    )


def test_the_hash_is_reproducible_from_the_mandate_alone(genesis: dict):
    """Recompute it independently. If the API simply echoed a value it invented,
    the equality above would still hold and prove nothing."""
    from agent.mandate.hashing import mandate_hash

    assert mandate_hash(Mandate.model_validate(GENESIS_MANDATE)) == genesis["mandate_hash"]


def test_the_mandate_reads_back_through_the_api(genesis: dict, api: str):
    """The vault page has to render the mandate for a vault this browser did not
    create — cross-lane request #6."""
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{api}/vault/{genesis['vault']}/mandate")
    assert response.status_code == 200
    stored = Mandate.model_validate(response.json())
    assert stored.name == GENESIS_MANDATE["name"]
    assert stored.constraints.min_cash_pct == GENESIS_MANDATE["constraints"]["min_cash_pct"]


def test_the_agent_can_act_on_the_new_vault(genesis: dict, api: str):
    """A vault whose agent is not the harness reads perfectly and reverts every
    write — the failure shape that looks healthy until the first execution."""
    with httpx.Client(timeout=30.0) as client:
        state = client.get(f"{api}/vault/{genesis['vault']}/state").json()
    assert state.get("agent"), "no AGENT_ROLE holder reported"


def test_a_second_genesis_deploys_a_different_vault(api: str, genesis: dict):
    """Genesis must not be idempotent. Two users with identical mandates need
    two vaults, and a factory returning the first one would silently pool their
    deposits."""
    with httpx.Client(timeout=120.0) as client:
        second = client.post(f"{api}/genesis/finalize", json={"mandate": GENESIS_MANDATE}).json()

    assert second["vault"] != genesis["vault"]
    # Same mandate, so the hash is identical — that is the point of a canonical
    # serialization, and it is what lets two vaults be compared.
    assert second["mandate_hash"] == genesis["mandate_hash"]
