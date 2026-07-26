"""Shared fixtures for the end-to-end suite.

Every lane tests its own component. This suite tests the thing no lane owns: the narrative running
through all of them at once. It talks only to public surfaces — JSON-RPC and the frozen HTTP API —
so it stays honest about what actually works rather than reaching into any lane's internals.

**Skips, never fails, when the stack is down.** A fresh clone running the full suite must stay
green; these tests are meaningful only against a running fork plus a live agent API. Follows the
same convention as `agent/tests/test_integration_lanes.py`.

Bring the stack up with `scripts/preflight.sh` — it will tell you exactly what is missing.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

import httpx
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
#: Same resolution the harness uses, so the suite cannot end up asserting
#: against a different network than the API is reading.
DEPLOYMENTS = pathlib.Path(
    os.getenv("DEPLOYMENTS_FILE")
    or REPO_ROOT / "deployments" / f"{os.getenv('DEPLOY_NETWORK') or 'base-fork'}.json"
)

RPC_URL = os.getenv("ANVIL_RPC_URL", "http://127.0.0.1:8540")
API_URL = os.getenv("NEXT_PUBLIC_API_URL", "http://localhost:8000")

#: anvil account #0 — the demo depositor. `scripts/seed-fork.sh` funds it.
DEPOSITOR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
DEPOSITOR_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
#: anvil account #1 — holds AGENT_ROLE. Account #0 reads fine and reverts every write.
AGENT = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


def _rpc(method: str, params: list[Any]) -> Any:
    with httpx.Client(timeout=15.0) as client:
        r = client.post(
            RPC_URL, json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        )
        r.raise_for_status()
        body = r.json()
    if "error" in body:
        raise RuntimeError(f"{method}: {body['error']}")
    return body["result"]


@pytest.fixture(scope="session")
def deployments() -> dict[str, Any]:
    if not DEPLOYMENTS.exists():
        pytest.skip(f"{DEPLOYMENTS.name} missing — deploy first (scripts/preflight.sh)")
    return json.loads(DEPLOYMENTS.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def fork(deployments: dict[str, Any]) -> str:
    """A reachable fork whose deployment actually exists on it.

    Checks bytecode rather than just liveness: after an anvil restart the RPC answers happily while
    every address in `base-fork.json` is empty, and the resulting failures look like contract bugs.
    """
    try:
        _rpc("eth_chainId", [])
    except Exception as exc:  # noqa: BLE001 - any failure means "no usable fork"
        pytest.skip(f"no fork at {RPC_URL} ({type(exc).__name__}) — run scripts/anvil-fork.sh")

    factory = deployments["contracts"]["VaultFactory"]
    if _rpc("eth_getCode", [factory, "latest"]) in ("0x", "0x0"):
        pytest.skip("factory has no bytecode — anvil restarted since the deploy; redeploy")
    return RPC_URL


@pytest.fixture(scope="session")
def api(fork: str) -> str:
    """The agent API, and only if it is genuinely live.

    Fixture mode is treated as absent rather than as a failure: every request would succeed and
    validate against golden data, so a green run would prove nothing. This is the single most
    valuable assertion in the file.
    """
    try:
        with httpx.Client(timeout=15.0) as client:
            health = client.get(f"{API_URL}/health").json()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"agent API unreachable at {API_URL} ({type(exc).__name__})")

    seams = (health.get("mode"), health.get("data_registry"), health.get("venue_registry"))
    if "fixture" in seams:
        pytest.skip(
            f"agent API is serving fixtures {seams} — restart with AGENT_MODE=live. "
            "Running e2e against fixtures would pass while proving nothing."
        )
    return API_URL


@pytest.fixture(scope="session")
def usdc(deployments: dict[str, Any]) -> str:
    return deployments["external"]["USDC"]


@pytest.fixture(scope="session")
def funded_depositor(fork: str, usdc: str) -> str:
    balance = int(
        _rpc(
            "eth_call",
            [{"to": usdc, "data": "0x70a08231" + "0" * 24 + DEPOSITOR[2:]}, "latest"],
        ),
        16,
    )
    if balance < 1_000_000_000:  # 1,000 USDC
        pytest.skip(f"depositor holds {balance / 1e6:.0f} USDC — run scripts/seed-fork.sh")
    return DEPOSITOR


@pytest.fixture(scope="session")
def w3(fork: str):
    """web3 client. Imported lazily so collection does not require the agent extra."""
    web3 = pytest.importorskip("web3", reason="web3 not installed — uv sync --all-extras")
    client = web3.Web3(web3.Web3.HTTPProvider(fork, request_kwargs={"timeout": 30}))
    if not client.is_connected():
        pytest.skip(f"web3 could not connect to {fork}")
    return client


def rpc(method: str, params: list[Any]) -> Any:
    """Raw JSON-RPC, for tests that want it without a web3 dependency."""
    return _rpc(method, params)


def factory_vaults(factory_address: str) -> list[str]:
    """Every vault the factory has created, from `vaults()`.

    `deployments/base-fork.json` is not enough and cannot be made enough: it records what
    `Deploy.s.sol` wrote, while genesis and one-click archetypes both mint through the factory
    without touching it. Those are the vaults that actually tick.
    """
    from eth_abi import decode as abi_decode

    raw = _rpc("eth_call", [{"to": factory_address, "data": "0x" + selector("vaults()")}, "latest"])
    if raw in ("0x", "0x0", None):
        return []
    (addresses,) = abi_decode(["address[]"], bytes.fromhex(raw[2:]))
    return [str(a) for a in addresses]


@pytest.fixture(scope="session")
def curated_vault(api: str, deployments: dict[str, Any]) -> str:
    """A vault that can actually be ticked: it has a stored mandate and holds something.

    ⚠️ **`deployments["demoVault"]` is not that vault and never can be.** It is created by
    `Deploy.s.sol`, and mandates are written only by `POST /genesis/finalize`, so it has none —
    every tick against it returns `status="failed"`, *"no mandate stored"*, with no snapshot and no
    decision attached.

    That is a quiet failure mode rather than a loud one, because tests that read the tick then skip
    on the missing snapshot. R3 reported five skips on every fresh fork and looked like a slow rung
    rather than an unproven one. `test_slice_wave2` had already learned this and read the factory;
    the lesson is hoisted here so the next file does not have to learn it a third time.

    Holdings matter as much as the mandate: a tick over an empty book has nothing to compare, so
    the richest vault is chosen rather than the first.
    """
    factory = deployments["contracts"]["VaultFactory"]
    best: tuple[int, str] | None = None
    with httpx.Client(timeout=30.0) as client:
        for vault in factory_vaults(factory):
            if client.get(f"{api}/vault/{vault}/mandate").status_code != 200:
                continue
            state = client.get(f"{api}/vault/{vault}/state")
            if state.status_code != 200:
                continue
            assets = int(state.json().get("total_assets") or 0)
            if best is None or assets > best[0]:
                best = (assets, vault)

    if best is None:
        pytest.skip(
            "no factory vault has a stored mandate — run genesis, or POST /archetypes/{key}/deploy"
        )
    if best[0] == 0:
        pytest.skip(
            f"the only mandated vaults are empty (richest is {best[1]}) — "
            "deposit into one, or run scripts/seed-fork.sh and deposit"
        )
    return best[1]


# ── createVault, across the version boundary Wave 3 opened ────────────────────
#
# `CreateParams` gained a 7th `deployer` field (Lane A's #94), so the published
# ABI and a fork that has not been redeployed disagree — and they disagree in
# both directions at once. Calling the 7-field selector against the old contract
# reverts with no message; passing 6 fields to the new ABI raises MismatchedABI
# before a transaction is ever built.
#
# Every e2e file that deploys a vault hit this simultaneously. Selecting on the
# DEPLOYED BYTECODE is the only check that stays right through the redeploy, so
# it lives here once rather than in each file: a redeploy mid-wave should not be
# able to red the suite, and a suite that goes red for a reason unrelated to what
# it tests teaches everyone to ignore it.

_CREATE_OLD = "createVault((address,string,string,address,address,bytes32))"
_CREATE_NEW = "createVault((address,string,string,address,address,bytes32,address))"

#: Where a vault with no named deployer is attributed. Only used against the
#: 7-field factory; the field does not exist on the old one.
UNATTRIBUTED_DEPLOYER = "0x0000000000000000000000000000000000000000"


def selector(signature: str) -> str:
    from eth_utils import keccak

    return keccak(text=signature)[:4].hex()


def factory_takes_deployer(factory_address: str) -> bool:
    """Whether the *deployed* factory is the 7-field version."""
    code = _rpc("eth_getCode", [factory_address, "latest"])
    if selector(_CREATE_NEW) in code:
        return True
    if selector(_CREATE_OLD) in code:
        return False
    pytest.skip("deployed factory exposes neither createVault signature — redeploy")


def create_vault_calldata(
    *,
    factory_address: str,
    asset: str,
    name: str,
    symbol: str,
    agent: str,
    guardian: str,
    mandate_hash: bytes,
    deployer: str = UNATTRIBUTED_DEPLOYER,
) -> str:
    """ABI-encoded `createVault` for whichever version is actually deployed.

    Hand-encoded rather than routed through `w3.eth.contract`, because the whole
    problem is that the contract object is built from an ABI file that may not
    describe the deployment.
    """
    from eth_abi import encode

    takes_deployer = factory_takes_deployer(factory_address)
    core = (asset, name, symbol, agent, guardian, mandate_hash)
    params = (*core, deployer) if takes_deployer else core
    signature = _CREATE_NEW if takes_deployer else _CREATE_OLD
    types = signature[signature.index("(") + 1 : signature.rindex(")")]
    return "0x" + selector(signature) + encode([types], [params]).hex()


def send_calldata(w3, *, to: str, data: str, sender: str, key: str):
    """Send pre-encoded calldata. The companion to `create_vault_calldata`."""
    tx = {
        "from": sender,
        "to": w3.to_checksum_address(to),
        "data": data,
        "gas": 3_000_000,
        "nonce": w3.eth.get_transaction_count(sender),
        "chainId": w3.eth.chain_id,
        # Hand-built rather than via `build_transaction`, which is what fills this in
        # normally — and omitting it does not produce a gas failure, it raises
        # `TypeError: Transaction must include these fields: {'gasPrice'}` at signing.
        "gasPrice": w3.eth.gas_price,
    }
    signed = w3.eth.account.sign_transaction(tx, key)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(raw), timeout=120)
    assert receipt.status == 1, f"createVault reverted: {receipt.transactionHash.hex()}"
    return receipt


def vault_created_by(w3, factory, before: list[str]) -> str:
    """The one vault `vaults()` gained, found by diff rather than by event decode.

    `VaultCreated` changed shape in the same wave the function did (`deployer`
    appended, `agent` demoted from topic to data), so decoding it with the
    published ABI against an older deployment fails for reasons unrelated to
    whatever the test is actually asserting.
    """
    planted = [v for v in factory.functions.vaults().call() if v not in before]
    assert len(planted) == 1, f"expected exactly one new vault, saw {planted}"
    return planted[0]
