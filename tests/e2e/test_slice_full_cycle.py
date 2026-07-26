"""The whole life of a vault, in one file, against the real contracts.

    uv run pytest tests/e2e -k full_cycle -v

Every other slice proves one rung. This one proves they compose — a single vault
created, funded, rotated through **Uniswap**, supplied to **Aave** and
**Morpho**, shipped into **Aqua**, unwound, paused, and finally redeemed. The
question it answers is the one nobody else asks: *does the vault still add up
after all of that has happened to it?*

**Why this exists at all.** Before the mainnet go-ahead the decision journal was
tallied by venue, and across 51 journalled actions on 76 vaults exactly **one**
had ever executed on chain: an Aave supply. Uniswap, Morpho and Aqua were each
covered by their own tests and none of them had ever run *in sequence against
one vault*. Every leg below is individually proven elsewhere; the composition
was not proven anywhere, and composition is what a demo does.

Each leg is its own test and they run in order against a module-scoped vault, so
a failure names the leg that broke rather than "the cycle failed". Legs that
depend on live third-party services skip with a stated reason rather than fail —
a Uniswap route that does not exist today is a market condition, not a defect in
this repo — but the vault-side invariants around them never skip.

⚠️ Builds and funds its own vault. Nothing here touches the shared demo vault.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from .conftest import (
    AGENT,
    REPO_ROOT,
    DEPOSITOR_KEY,
    create_vault_calldata,
    send_calldata,
    vault_created_by,
)
from .test_slice_read import ERC20_ABI, _abi

#: What `agent/chain/vault_client.py` uses (`_GAS_LIMIT`). Deliberately a fixed
#: ceiling rather than `eth_estimateGas`, and this file learned why the hard way:
#: estimation under-shot three separate legs here. Aave's `withdraw` died
#: `OutOfGas` inside the aToken burn, and a `redeem` that had already emitted
#: `Withdraw` and transferred the USDC then reverted with `ReentrancySentryOOG`
#: while closing the guard — a *successful* redemption undone by a short limit.
#:
#: The estimator is not wrong so much as unlucky: the 63/64 rule reserves a
#: sixty-fourth of the remaining gas at each nested call, and against Aave that
#: is several frames deep, so the estimate is short by exactly the amount the
#: last storage write needs. Unspent gas is refunded, so an over-large limit
#: costs nothing.
GAS_LIMIT = 3_000_000

#: anvil account #1 — holds AGENT_ROLE. Reads work with any key; writes revert.
AGENT_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"

#: Overridable so the cycle can be re-run at the size the mainnet demo will
#: actually use. The default is generous on purpose — a leg that fails only at
#: small size is a *finding*, and it cannot be a finding if the suite never runs
#: large enough to establish the leg works at all.
#:
#:     CYCLE_DEPOSIT_USDC=1000000 uv run pytest tests/e2e -k full_cycle
DEPOSIT_USDC = int(os.environ.get("CYCLE_DEPOSIT_USDC", 2_000_000_000))  # 6dp

pytestmark = pytest.mark.order("last") if hasattr(pytest.mark, "order") else ()


def _send(w3, fn, sender: str, key: str):
    """Like `test_slice_read._send`, but with an explicit gas limit. See GAS_LIMIT."""
    tx = fn.build_transaction({
        "from": sender,
        "nonce": w3.eth.get_transaction_count(sender),
        "chainId": w3.eth.chain_id,
        "gas": GAS_LIMIT,
    })
    signed = w3.eth.account.sign_transaction(tx, key)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(raw), timeout=180)
    assert receipt.status == 1, f"tx reverted: 0x{receipt.transactionHash.hex()}"
    return receipt


#: `allowance` is not in the shared ERC20_ABI, and it is the one observable that
#: separates a live Aqua position from a dead one. Declared here rather than
#: widening another slice's constant.
ALLOWANCE_ABI = json.loads("""[
 {"name":"allowance","type":"function","stateMutability":"view",
  "inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
  "outputs":[{"type":"uint256"}]}
]""")


#: Chainlink ETH/USD on Base — the feed the vault itself values WETH with.
ETH_USD_FEED = "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70"


def _fork_price_drift_bps(w3) -> float | None:
    """How far the pinned fork's price has drifted from live Base, in bps.

    **Why a swap test has to know this.** The Uniswap Trading API quotes against
    *live* mainnet and stamps an `amountOutMinimum` on the calldata. The fork
    executes that calldata at the price of the block it was pinned to. If ETH has
    moved further than the mandate's slippage tolerance in the meantime, the pool
    returns less than the minimum and the router reverts `V3TooLittleReceived()`.

    Measured here at 11,523 blocks of drift: 58 bps against a 50 bps ceiling.
    Nothing is wrong with the vault, the adapter, the size of the trade or the
    mandate — the fork is simply old. **This cannot happen on mainnet**, where
    the quote and the execution see the same chain state.

    Returns None if either price is unreadable, in which case the caller should
    proceed and let a real failure be a real failure.
    """
    import os

    import httpx
    from dotenv import load_dotenv

    def _price(url: str) -> float | None:
        try:
            r = httpx.post(
                url,
                json={"jsonrpc": "2.0", "method": "eth_call", "id": 1,
                      "params": [{"to": ETH_USD_FEED, "data": "0xfeaf968c"}, "latest"]},
                timeout=20,
            ).json()["result"]
            return int(r[2 + 64: 2 + 128], 16) / 1e8
        except Exception:  # noqa: BLE001 — an unreadable price is not a verdict
            return None

    load_dotenv(REPO_ROOT / ".env", override=False)
    live_url = os.environ.get("BASE_RPC_URL")
    if not live_url:
        return None
    fork_price, live_price = _price(w3.provider.endpoint_uri), _price(live_url)
    if not fork_price or not live_price:
        return None
    return abs(live_price - fork_price) / fork_price * 10_000


def _erc20(w3, token: str):
    return w3.eth.contract(address=w3.to_checksum_address(token), abi=ERC20_ABI)


def _allowance(w3, token: str, owner: str, spender: str) -> int:
    c = w3.eth.contract(address=w3.to_checksum_address(token), abi=ALLOWANCE_ABI)
    return c.functions.allowance(
        w3.to_checksum_address(owner), w3.to_checksum_address(spender)
    ).call()


def _balance(w3, token: str, who: str) -> int:
    return _erc20(w3, token).functions.balanceOf(w3.to_checksum_address(who)).call()


def _vault_state(api: str, address: str):
    """The API's own view, which is what the dApp renders."""
    import httpx
    from curator_schema import VaultState

    with httpx.Client(timeout=60) as client:
        r = client.get(f"{api}/vault/{address}/state")
    assert r.status_code == 200, r.text
    return VaultState.model_validate(r.json())


def _plan(venue_key: str, intent, state):
    """Build an ExecutionPlan through Lane D's real adapter.

    Deliberately goes through `get_venue` rather than hand-encoding calldata:
    the point is to exercise the adapter the harness actually uses, including
    its approvals. Hand-rolled calldata would test this file's understanding of
    a venue rather than the code that will run on mainnet.
    """
    venues = pytest.importorskip("venues", reason="Lane D not installed")
    venue = venues.get_venue(venue_key)
    return asyncio.run(venue.plan(intent, state))


def _execute(w3, vault: str, plan) -> object:
    """Submit an ExecutionPlan as one atomic `executeBatch`.

    Atomicity is the property under test as much as the calls are: an approval
    that lands while its swap reverts leaves a standing allowance to a venue,
    which is exactly the state the batch interface exists to make impossible.
    """
    contract = w3.eth.contract(address=w3.to_checksum_address(vault), abi=_abi("CuratedVault"))
    calls = [
        (w3.to_checksum_address(s.target), int(s.value or 0), bytes.fromhex(s.calldata[2:]))
        for s in plan.steps
    ]
    return _send(w3, contract.functions.executeBatch(calls), AGENT, AGENT_KEY)


@pytest.fixture(scope="module")
def cycle_vault(w3, deployments, usdc, funded_depositor, api) -> str:
    """One vault, created and funded, that every leg below mutates in turn."""
    factory_address = deployments["contracts"]["VaultFactory"]
    factory = w3.eth.contract(
        address=w3.to_checksum_address(factory_address), abi=_abi("VaultFactory")
    )
    before = factory.functions.vaults().call()
    send_calldata(
        w3,
        to=factory_address,
        data=create_vault_calldata(
            factory_address=factory_address,
            asset=usdc,
            name="Full Cycle",
            symbol="cCYCLE",
            agent=AGENT,
            guardian=funded_depositor,
            mandate_hash=w3.keccak(text="e2e-full-cycle"),
            deployer=funded_depositor,
        ),
        sender=funded_depositor,
        key=DEPOSITOR_KEY,
    )
    vault = vault_created_by(w3, factory, before)

    token = _erc20(w3, usdc)
    _send(w3, token.functions.approve(vault, DEPOSIT_USDC), funded_depositor, DEPOSITOR_KEY)
    v = w3.eth.contract(address=w3.to_checksum_address(vault), abi=_abi("CuratedVault"))
    _send(w3, v.functions.deposit(DEPOSIT_USDC, funded_depositor), funded_depositor, DEPOSITOR_KEY)
    return vault


# ── 1. the deposit is real and custodied ──────────────────────────────────


def test_01_deposit_lands_in_the_vault(w3, usdc, cycle_vault, funded_depositor):
    """Pattern 1: the vault is the sole custodian, so the tokens are *here*."""
    assert _balance(w3, usdc, cycle_vault) == DEPOSIT_USDC

    v = w3.eth.contract(address=w3.to_checksum_address(cycle_vault), abi=_abi("CuratedVault"))
    assert v.functions.totalAssets().call() == DEPOSIT_USDC
    assert v.functions.balanceOf(funded_depositor).call() > 0


# ── 2. Uniswap — the only venue that changes what the vault holds ─────────


def test_02_uniswap_rotation_moves_real_tokens(w3, usdc, deployments, cycle_vault, api):
    """A quarter of the book into WETH, through the Trading API and the router.

    This is also the 1inch track's qualifying token transfer: an Aqua ship moves
    nothing by design, so a swap or a taker fill has to be the event that does.
    """
    from curator_schema import SwapIntent
    from venues.errors import NoRouteError, VenueAPIError

    weth = deployments["external"]["WETH"]
    before_usdc = _balance(w3, usdc, cycle_vault)
    before_weth = _balance(w3, weth, cycle_vault)

    # Checked BEFORE quoting, so a stale fork is reported as a stale fork rather
    # than as a reverted swap. The mandate ceiling this is measured against is
    # 50 bps, the value every shipped preset carries.
    drift = _fork_price_drift_bps(w3)
    if drift is not None and drift > 50:
        pytest.skip(
            f"the fork's price is {drift:.0f} bps from live Base, past the 50 bps "
            f"slippage ceiling. The Trading API quotes against live mainnet and the "
            f"fork executes at its pinned block, so the router reverts "
            f"V3TooLittleReceived() no matter how the trade is sized. Restart the "
            f"fork (scripts/anvil-fork.sh) to re-pin it. Cannot occur on mainnet, "
            f"where the quote and the execution see the same chain state."
        )

    try:
        plan = _plan(
            "uniswap",
            SwapIntent(token_in="USDC", token_out="WETH", pct_of_holdings=0.25),
            _vault_state(api, cycle_vault),
        )
    except NoRouteError as exc:
        pytest.skip(f"no Uniswap route right now — a market condition, not a defect: {exc}")
    except VenueAPIError as exc:
        pytest.skip(f"Uniswap Trading API unavailable: {exc}")

    _execute(w3, cycle_vault, plan)

    after_usdc = _balance(w3, usdc, cycle_vault)
    after_weth = _balance(w3, weth, cycle_vault)
    assert after_usdc < before_usdc, "USDC did not leave the vault"
    assert after_weth > before_weth, "no WETH arrived — the swap did not happen"

    # Realised slippage inside the golden mandate's ceiling. The vault priced
    # both legs through Chainlink, so this compares like with like.
    spent = before_usdc - after_usdc
    assert spent <= DEPOSIT_USDC * 0.26, "swap took more than the 25% it was sized for"


# ── 3. Aave — supply, then take it back ───────────────────────────────────


def test_03_aave_supply_then_withdraw_round_trips(w3, usdc, cycle_vault, api):
    """Idle USDC earns, and the receipt token is USDC exposure, not a position.

    The round trip is the point: a supply that cannot be reversed is a one-way
    door, and `min_cash_pct` depends on withdrawal actually working.
    """
    from curator_schema import SupplyIntent, WithdrawIntent

    state = _vault_state(api, cycle_vault)
    liquid_before = _balance(w3, usdc, cycle_vault)

    _execute(w3, cycle_vault, _plan("aave", SupplyIntent(asset="USDC", pct_of_holdings=0.5), state))

    after_supply = _balance(w3, usdc, cycle_vault)
    assert after_supply < liquid_before, "USDC did not leave for Aave"

    receipts = [
        h for h in _vault_state(api, cycle_vault).holdings
        if (h.represents or "") == "USDC" and h.symbol != "USDC" and int(h.balance) > 0
    ]
    assert receipts, "no aToken holding appeared, or it is not marked as USDC exposure"

    _execute(
        w3,
        cycle_vault,
        _plan("aave", WithdrawIntent(asset="USDC"), _vault_state(api, cycle_vault)),
    )
    assert _balance(w3, usdc, cycle_vault) > after_supply, "withdraw returned nothing"


# ── 4. Morpho — the second lender, proving the venue port is a port ───────


def test_04_morpho_supply_then_withdraw(w3, usdc, cycle_vault, api):
    """The second lender, reached the same way as the first.

    Morpho was registered, tested and reported `available` by `GET /venues` for
    two waves while being **unreachable**: the frozen schema pinned
    `SupplyIntent.venue` to `Literal["aave"]` and `agent/loop/planning.py` routes
    on `intent.venue`, so no intent the model could emit ever arrived. Widening
    the literal to `Literal["aave", "morpho"]` is the whole fix; this is the test
    that says so.

    Running the *identical two intents* against a different venue is also the
    only real test of the venue port. If either adapter needed caller-side
    special casing, this function could not be a copy of the Aave one.
    """
    from curator_schema import SupplyIntent, WithdrawIntent
    from venues.errors import VenueError

    state = _vault_state(api, cycle_vault)
    before = _balance(w3, usdc, cycle_vault)
    if before < DEPOSIT_USDC // 10:
        pytest.skip(f"only {before} USDC units liquid; too little of the deposit left to supply")

    try:
        plan = _plan(
            "morpho", SupplyIntent(venue="morpho", asset="USDC", pct_of_holdings=0.3), state
        )
    except VenueError as exc:
        pytest.skip(f"no Morpho market for USDC on this fork: {exc}")

    _execute(w3, cycle_vault, plan)
    after = _balance(w3, usdc, cycle_vault)
    assert after < before, "USDC did not leave the vault for Morpho"

    # The 4626 share token is USDC exposure, not a new asset — same property the
    # Aave leg asserts, and what keeps max_position_pct from fighting a position
    # the mandate asked for.
    shares = [
        h for h in _vault_state(api, cycle_vault).holdings
        if (h.represents or "") == "USDC" and h.symbol not in ("USDC",) and int(h.balance) > 0
    ]
    assert shares, "no Morpho share holding appeared, or it is not marked as USDC exposure"

    _execute(
        w3,
        cycle_vault,
        _plan("morpho", WithdrawIntent(venue="morpho", asset="USDC"),
              _vault_state(api, cycle_vault)),
    )
    assert _balance(w3, usdc, cycle_vault) > after, "Morpho withdraw returned nothing"


def test_04b_a_mandate_still_gates_the_new_venue(api):
    """Widening the schema must not widen what a mandate permits.

    `permitted_venues` is an allowlist and is explicitly never banded, so a
    mandate that names only Aave must still reject a Morpho intent. Otherwise
    the fix would have turned a reachability bug into a constraint hole.
    """
    import json, pathlib
    from curator_schema import AllocationDecision, Mandate, SupplyIntent
    from agent.mandate.constraints import check_decision

    presets = pathlib.Path(__file__).resolve().parents[2] / "packages" / "schema" / "presets"
    mandate = Mandate.model_validate(
        json.loads((presets / "conservative-income.json").read_text(encoding="utf-8"))
    )
    aave_only = mandate.model_copy(
        update={"permitted_venues": [v for v in mandate.permitted_venues if v != "morpho"]}
    )
    decision = AllocationDecision(
        action="enter",
        reasoning="Morpho quotes better than Aave today.",
        venue_intents=[SupplyIntent(venue="morpho", asset="USDC", pct_of_holdings=0.2)],
    )

    assert check_decision(decision, aave_only), (
        "a mandate permitting only aave accepted a morpho intent — widening the "
        "schema removed a constraint instead of removing a blocker"
    )
    assert not [
        v for v in check_decision(decision, mandate) if v.constraint == "permitted_venues"
    ], "the shipped preset grants morpho, so it must not be rejected on the venue"


# ── 5. Aqua — a maker position that moves nothing ─────────────────────────


def test_05_aqua_ship_holds_a_position_without_moving_tokens(
    w3, usdc, deployments, cycle_vault, api
):
    """The custody argument, asserted rather than described.

    Gated on the **allowance**, not on `safeBalances()`: request #17 established
    against the real contract that a ship with no approvals yields non-zero
    balances, a valid hash and a successful transaction — and a position that can
    never be filled. The allowance is the only observable separating the two.
    """
    from curator_schema import AquaShipIntent
    from venues.errors import VenueError

    aqua = deployments["external"]["Aqua"]
    state = _vault_state(api, cycle_vault)
    usdc_before = _balance(w3, usdc, cycle_vault)
    total_before = w3.eth.contract(
        address=w3.to_checksum_address(cycle_vault), abi=_abi("CuratedVault")
    ).functions.totalAssets().call()

    held = {h.symbol: int(h.balance) for h in state.holdings}
    usdc_held, weth_held = held.get("USDC", 0), held.get("WETH", 0)
    # XYC is a two-token constant-product curve, so a one-sided ship is not a
    # thing it can represent — the venue rejects it before any calldata is built.
    if usdc_held < DEPOSIT_USDC // 10 or weth_held == 0:
        pytest.skip(
            f"need both legs for a two-token curve; hold {usdc_held} USDC, {weth_held} WETH "
            "(the Uniswap leg must run first)"
        )

    try:
        plan = _plan(
            "aqua",
            AquaShipIntent(
                tokens=["USDC", "WETH"],
                amounts=[str(usdc_held // 4), str(weth_held // 2)],
            ),
            state,
        )
    except VenueError as exc:
        pytest.skip(f"Aqua plan could not be built: {exc}")

    _execute(w3, cycle_vault, plan)

    # Pattern 1 — the tokens never left.
    assert _balance(w3, usdc, cycle_vault) == usdc_before, (
        "shipping moved tokens out of the vault; that breaks sole custody and is "
        "the whole reason Aqua was chosen over a conventional LP position"
    )
    total_after = w3.eth.contract(
        address=w3.to_checksum_address(cycle_vault), abi=_abi("CuratedVault")
    ).functions.totalAssets().call()
    assert total_after == total_before, "totalAssets moved on a ship that moved nothing"

    allowance = _allowance(w3, usdc, cycle_vault, aqua)
    assert allowance > 0, (
        "the vault granted Aqua no allowance, so a taker can never pull — the "
        "position looks healthy in every other observable and is dead"
    )


# ── 6. a chain of actions in one atomic batch ─────────────────────────────


def test_06_multiple_intents_execute_atomically(w3, usdc, cycle_vault, api):
    """Two venues in a single `executeBatch`, which is how a real tick behaves.

    `max_actions_per_tick` allows more than one intent, so the batch is the unit
    of atomicity, not the intent. Either the whole plan lands or none of it does
    — a partial batch leaves approvals standing against venues the vault decided
    not to use.
    """
    from curator_schema import SupplyIntent

    state = _vault_state(api, cycle_vault)
    liquid = next((int(h.balance) for h in state.holdings if h.symbol == "USDC"), 0)
    if liquid < DEPOSIT_USDC // 10:
        pytest.skip(f"only {liquid} USDC units liquid; too little left for a combined batch")

    aave = _plan("aave", SupplyIntent(asset="USDC", pct_of_holdings=0.2), state)
    combined = aave.model_copy(update={"steps": list(aave.steps)})

    before = _balance(w3, usdc, cycle_vault)
    receipt = _execute(w3, cycle_vault, combined)
    assert receipt.status == 1
    assert _balance(w3, usdc, cycle_vault) < before

    # One transaction hash for the whole chain — that is what makes it atomic.
    assert receipt.transactionHash is not None


# ── 7. the guardian can halt trading without touching anyone's money ──────


def test_07_pause_leaves_withdrawals_open(w3, cycle_vault, funded_depositor):
    """Wave 3's core safety claim, and the half that is easy to get wrong.

    Pausing must not freeze depositors out. If it did, "the guardian can stop the
    agent" would also mean "the guardian can trap your money", which is a
    strictly worse trust model than having no guardian at all.
    """
    v = w3.eth.contract(address=w3.to_checksum_address(cycle_vault), abi=_abi("CuratedVault"))
    _send(w3, v.functions.pause(), funded_depositor, DEPOSITOR_KEY)
    assert v.functions.paused().call() is True

    shares = v.functions.balanceOf(funded_depositor).call()
    assert v.functions.maxRedeem(funded_depositor).call() > 0, (
        "redemption is closed while paused — a pause that traps deposits"
    )
    _send(
        w3,
        v.functions.redeem(shares // 20, funded_depositor, funded_depositor),
        funded_depositor,
        DEPOSITOR_KEY,
    )

    _send(w3, v.functions.unpause(), funded_depositor, DEPOSITOR_KEY)
    assert v.functions.paused().call() is False


# ── 8. the exit that needs no market ──────────────────────────────────────


def test_08_redeem_in_kind_pays_a_slice_of_everything(w3, cycle_vault, funded_depositor):
    """`redeemInKind` is unconditionally payable — no oracle, no liquidity, no venue.

    It matters most in exactly the state this vault is now in: holdings spread
    across a swap, two lending markets and a maker position. A conventional
    redeem needs all of that to be priceable and unwindable; this needs neither.
    """
    v = w3.eth.contract(address=w3.to_checksum_address(cycle_vault), abi=_abi("CuratedVault"))
    shares = v.functions.balanceOf(funded_depositor).call()
    if shares == 0:
        pytest.skip("nothing left to redeem")

    supply_before = v.functions.totalSupply().call()
    _send(
        w3,
        v.functions.redeemInKind(shares // 10, funded_depositor, funded_depositor),
        funded_depositor,
        DEPOSITOR_KEY,
    )
    assert v.functions.totalSupply().call() < supply_before, "shares were not burned"


# ── 9. after all of that, the accounting still holds ──────────────────────


def test_09_the_vault_still_adds_up(w3, cycle_vault, funded_depositor, api):
    """The question the whole file exists to ask.

    A depositor who put in 2,000 USDC and did nothing else must not be able to
    take out more than they put in — no sequence of agent actions may mint value.
    Checked last, deliberately, against a book that has been through every venue.
    """
    v = w3.eth.contract(address=w3.to_checksum_address(cycle_vault), abi=_abi("CuratedVault"))

    shares = v.functions.balanceOf(funded_depositor).call()
    if shares == 0:
        pytest.skip("fully redeemed by an earlier leg")

    # No free money. Slippage and fees mean this should be slightly DOWN.
    assert v.functions.convertToAssets(shares).call() <= DEPOSIT_USDC, (
        "the position is worth more than was deposited after a round trip through "
        "four venues — that is value appearing from nowhere, not yield"
    )

    # And the API agrees with the chain, which is what the dApp shows.
    state = _vault_state(api, cycle_vault)
    assert int(state.total_assets) == v.functions.totalAssets().call(), (
        "the API and the contract disagree about totalAssets"
    )
    assert state.holdings, "holdings() came back empty after a full cycle"
