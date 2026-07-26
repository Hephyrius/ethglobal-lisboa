"""Recording open Aqua positions — the obligation the harness never met.

`venues/README.md` states it plainly: *"the harness must record the tokens at
`ship()` time. Without it, docking raises rather than guessing."* Nothing did,
so `VaultState.aqua_strategies` was `[]` forever, with two consequences:

* the dApp's `AquaPositions` panel returns null on an empty list, so **no open
  Aqua position was ever displayed**; and
* **`dock()` could never be built**, because `AquaVenue._tokens_for_strategy`
  looks the strategy up in exactly that list.

The second is the one that has no symptom until something tries to close a
position, which is why these tests assert the token list as hard as the hash.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from curator_schema import ExecutionPlan, ExecutionStep

from agent.chain.aqua_positions import AquaPositionStore, strategies_from_plan

pytest.importorskip("venues.aqua", reason="Lane D's venue package is optional")

from venues.aqua import approve_step, dock_step, ship_step  # noqa: E402

# Base mainnet USDC and WETH — public contract addresses, not secrets. Both are
# already in `deployments/base-fork.json` and `venues/addresses.py`; the scanner
# flags any 40-hex assignment, which is the right default for a repo that has
# already leaked a private key once.
TOKEN_A = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"  # USDC · secrets-check: allow
TOKEN_B = "0x4200000000000000000000000000000000000006"  # WETH · secrets-check: allow
STRATEGY = "0x" + "ab" * 64
VAULT = "0xc90E6473df8371416c362D70fe2E6335E1c31414"


def _ship_plan() -> ExecutionPlan:
    """A ship exactly as Lane D emits it: two approvals, then the ship."""
    return ExecutionPlan(
        venue="aqua",
        steps=[
            approve_step(TOKEN_A, 1_000),
            approve_step(TOKEN_B, 2_000),
            ship_step(STRATEGY, [TOKEN_A, TOKEN_B], [1_000, 2_000]),
        ],
    )


def test_the_hash_is_the_keccak_of_the_strategy_bytes():
    """The property the whole fix rests on, verified against the live builder
    before it was relied on: `strategy_hash == keccak256(strategy)`.

    That is what makes the hash derivable from calldata the harness already
    stores, rather than needing Lane D to surface a value its plan currently
    carries only truncated to ten characters inside prose.
    """
    from eth_utils import keccak

    opened, _ = strategies_from_plan(_ship_plan())
    assert len(opened) == 1
    assert opened[0].strategy_hash == "0x" + keccak(bytes.fromhex(STRATEGY[2:])).hex()


def test_a_ship_records_its_tokens():
    """The token list is the part `dock()` cannot be built without."""
    opened, closed = strategies_from_plan(_ship_plan())
    assert closed == []
    assert [t.lower() for t in opened[0].tokens] == [TOKEN_A, TOKEN_B]
    assert opened[0].shipped_at is not None


def test_approvals_are_not_mistaken_for_ships():
    """Every step of every executed plan runs through this, so a non-ship step
    has to be ignored rather than raise or half-match."""
    plan = ExecutionPlan(venue="aqua", steps=[approve_step(TOKEN_A, 1_000)])
    assert strategies_from_plan(plan) == ([], [])


def test_a_uniswap_plan_records_nothing():
    plan = ExecutionPlan(
        venue="uniswap",
        steps=[ExecutionStep(target=TOKEN_A, value="0", calldata="0xdeadbeef", why="swap")],
    )
    assert strategies_from_plan(plan) == ([], [])


def test_a_dock_closes_the_position_it_names():
    from eth_utils import keccak

    strategy_hash = "0x" + keccak(bytes.fromhex(STRATEGY[2:])).hex()
    plan = ExecutionPlan(
        venue="aqua", steps=[dock_step(strategy_hash, [TOKEN_A, TOKEN_B])]
    )
    opened, closed = strategies_from_plan(plan)
    assert opened == []
    assert [h.lower() for h in closed] == [strategy_hash.lower()]


# ── the store ─────────────────────────────────────────────────────────────


def test_ship_then_dock_leaves_nothing_open(tmp_path: Path):
    store = AquaPositionStore(tmp_path)

    opened, closed = strategies_from_plan(_ship_plan())
    store.apply(VAULT, opened, closed)
    assert len(store.read(VAULT)) == 1

    docked = ExecutionPlan(
        venue="aqua", steps=[dock_step(opened[0].strategy_hash, [TOKEN_A, TOKEN_B])]
    )
    store.apply(VAULT, *strategies_from_plan(docked))
    assert store.read(VAULT) == []


def test_shipping_the_same_strategy_twice_is_one_position(tmp_path: Path):
    """The venue derives a stable hash for the same program, so a retried tick
    must not leave the dApp reporting two positions where one exists."""
    store = AquaPositionStore(tmp_path)
    opened, closed = strategies_from_plan(_ship_plan())
    store.apply(VAULT, opened, closed)
    store.apply(VAULT, opened, closed)
    assert len(store.read(VAULT)) == 1


def test_positions_survive_a_restart(tmp_path: Path):
    """A live maker position outliving the process is the whole point of a file:
    lose it and the position is neither showable nor dockable, with nothing on
    chain to recover it from."""
    opened, closed = strategies_from_plan(_ship_plan())
    AquaPositionStore(tmp_path).apply(VAULT, opened, closed)

    reread = AquaPositionStore(tmp_path).read(VAULT)
    assert len(reread) == 1
    assert [t.lower() for t in reread[0].tokens] == [TOKEN_A, TOKEN_B]


def test_a_vault_that_never_shipped_reads_empty(tmp_path: Path):
    assert AquaPositionStore(tmp_path).read(VAULT) == []


def test_one_vaults_positions_do_not_leak_into_another(tmp_path: Path):
    store = AquaPositionStore(tmp_path)
    opened, closed = strategies_from_plan(_ship_plan())
    store.apply(VAULT, opened, closed)
    assert store.read("0x0000000000000000000000000000000000000001") == []
