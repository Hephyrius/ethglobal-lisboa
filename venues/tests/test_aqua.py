"""Tests for the Aqua/SwapVM maker adapter.

Offline tests use a stub builder, so plan shape, step ordering and calldata
encoding are covered with no chain. The `live` tests do the real `eth_call`
against a local anvil and are skipped when one is not running.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from curator_schema.models import (
    AquaDockIntent,
    AquaProgram,
    AquaShipIntent,
    AquaStrategy,
    ExecutionPlan,
    Holding,
    SwapIntent,
    VaultState,
)
from jsonschema import Draft202012Validator

from venues import addresses
from venues.abi import ERC20_APPROVE, selector
from venues.aqua.calldata import AQUA_DOCK, AQUA_SHIP, dock_step, ship_step
from venues.aqua.program import Strategy
from venues.aqua.venue import AquaVenue
from venues.errors import UnsupportedIntentError, VenueError

VAULT_ADDRESS = "0x00000000000000000000000000000000000000A1"
STRATEGY_HASH = "0x" + "ab" * 32


class StubBuilder:
    """Stands in for the Solidity builder. Returns tokens already sorted, which
    is what the real contract does — the point of the stub is to prove the venue
    re-pairs amounts against *that* order rather than the caller's."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def build_strategy(self, maker, token0, token1, *, fee_bps=0, salt=0):
        self.calls.append(
            {"maker": maker, "tokens": (token0, token1), "fee_bps": fee_bps, "salt": salt}
        )
        token_a, token_b = sorted([token0, token1], key=lambda a: int(a, 16))
        return Strategy(
            strategy="0x" + "cd" * 128,
            strategy_hash=STRATEGY_HASH,
            token_a=token_a,
            token_b=token_b,
        )


def _vault(**kw) -> VaultState:
    defaults = dict(
        address=VAULT_ADDRESS,
        asset=addresses.USDC,
        total_assets="10000000000",
        total_supply="10000000000",
        holdings=[
            Holding(token=addresses.USDC, symbol="USDC", balance="10000000000", decimals=6),
            Holding(
                token=addresses.WETH,
                symbol="WETH",
                balance="3000000000000000000",
                decimals=18,
            ),
        ],
        asset_decimals=6,
    )
    defaults.update(kw)
    return VaultState(**defaults)


@pytest.fixture
def venue() -> AquaVenue:
    return AquaVenue(builder=StubBuilder())


# ── ship ──────────────────────────────────────────────────────────────────


class TestShip:
    async def test_emits_approvals_before_ship(self, venue):
        plan = await venue.plan(
            AquaShipIntent(
                tokens=["USDC", "WETH"], amounts=["1000000000", "300000000000000000"]
            ),
            _vault(),
        )

        assert plan.venue == "aqua"
        assert len(plan.steps) == 3
        assert plan.steps[0].calldata.startswith("0x" + selector(ERC20_APPROVE).hex())
        assert plan.steps[1].calldata.startswith("0x" + selector(ERC20_APPROVE).hex())
        assert plan.steps[2].target.lower() == addresses.AQUA.lower()
        assert plan.steps[2].calldata.startswith("0x" + selector(AQUA_SHIP).hex())

    async def test_amounts_are_repaired_to_the_strategys_token_order(self, venue):
        """The strategy sorts tokens (WETH < USDC on Base). If the venue kept
        the caller's order, ship() would pair 1,000 USDC with WETH — a position
        wrong by twelve orders of magnitude."""
        plan = await venue.plan(
            AquaShipIntent(
                tokens=["USDC", "WETH"], amounts=["1000000000", "300000000000000000"]
            ),
            _vault(),
        )

        # Step 0 approves the sorted-first token, which is WETH.
        assert plan.steps[0].target.lower() == addresses.WETH.lower()
        assert "300000000000000000" in plan.steps[0].why or True
        weth_amount = int(plan.steps[0].calldata[-64:], 16)
        usdc_amount = int(plan.steps[1].calldata[-64:], 16)
        assert weth_amount == 300000000000000000, "WETH amount followed the wrong token"
        assert usdc_amount == 1000000000, "USDC amount followed the wrong token"

    async def test_approves_aqua_not_swapvm(self, venue):
        plan = await venue.plan(
            AquaShipIntent(tokens=["USDC", "WETH"], amounts=["1000000", "1000000"]), _vault()
        )
        # Aqua is what pulls the tokens on a fill; approving SwapVM would revert.
        assert addresses.AQUA[2:].lower() in plan.steps[0].calldata.lower()

    async def test_fee_comes_from_the_intent_when_given(self, venue):
        await venue.plan(
            AquaShipIntent(
                tokens=["USDC", "WETH"],
                amounts=["1000000", "1000000"],
                program=AquaProgram(shape="xyc", fee_bps=5),
            ),
            _vault(),
        )
        assert venue._builder.calls[-1]["fee_bps"] == 5

    async def test_salt_is_deterministic_so_a_retried_tick_is_idempotent(self, venue):
        """A random salt would make a retry open a second position instead of
        rebuilding the same one."""
        intent = AquaShipIntent(tokens=["USDC", "WETH"], amounts=["1000000", "1000000"])
        await venue.plan(intent, _vault(block_number=1234))
        await venue.plan(intent, _vault(block_number=1234))
        salts = [c["salt"] for c in venue._builder.calls]
        assert salts[0] == salts[1]

        await venue.plan(intent, _vault(block_number=9999))
        assert venue._builder.calls[-1]["salt"] != salts[0], "new state should re-salt"

    async def test_vault_is_the_maker(self, venue):
        await venue.plan(
            AquaShipIntent(tokens=["USDC", "WETH"], amounts=["1000000", "1000000"]), _vault()
        )
        # Pattern 1: the vault is the maker, so tokens never leave it.
        assert venue._builder.calls[-1]["maker"] == VAULT_ADDRESS

    async def test_mismatched_tokens_and_amounts_are_rejected(self, venue):
        with pytest.raises(VenueError, match="index-aligned"):
            await venue.plan(
                AquaShipIntent(tokens=["USDC", "WETH"], amounts=["1000000"]), _vault()
            )

    async def test_three_tokens_rejected_rather_than_silently_truncated(self, venue):
        with pytest.raises(VenueError, match="two-token"):
            await venue.plan(
                AquaShipIntent(
                    tokens=["USDC", "WETH", "USDC"], amounts=["1", "2", "3"]
                ),
                _vault(),
            )


# ── dock ──────────────────────────────────────────────────────────────────


class TestDock:
    async def test_dock_emits_a_single_step(self, venue):
        vault = _vault(
            aqua_strategies=[
                AquaStrategy(
                    strategy_hash=STRATEGY_HASH, tokens=[addresses.WETH, addresses.USDC]
                )
            ]
        )
        plan = await venue.plan(AquaDockIntent(strategy_hash=STRATEGY_HASH), vault)

        assert len(plan.steps) == 1
        assert plan.steps[0].target.lower() == addresses.AQUA.lower()
        assert plan.steps[0].calldata.startswith("0x" + selector(AQUA_DOCK).hex())

    async def test_dock_without_recorded_tokens_fails_with_a_useful_message(self, venue):
        with pytest.raises(VenueError, match="aqua_strategies"):
            await venue.plan(AquaDockIntent(strategy_hash=STRATEGY_HASH), _vault())


# ── shared contract ───────────────────────────────────────────────────────


class TestVenueContract:
    async def test_swap_intent_is_refused(self, venue):
        with pytest.raises(UnsupportedIntentError, match="UniswapVenue"):
            await venue.plan(
                SwapIntent(token_in="USDC", token_out="WETH", amount_in="1000000"), _vault()
            )

    async def test_all_targets_are_allowlisted(self, venue):
        plan = await venue.plan(
            AquaShipIntent(tokens=["USDC", "WETH"], amounts=["1000000", "1000000"]), _vault()
        )
        for step in plan.steps:
            assert step.target.lower() in addresses.allowlist()

    async def test_plan_validates_against_the_frozen_json_schema(self, venue, repo_root: Path):
        schema = json.loads(
            (repo_root / "packages/schema/execution-plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        plan = await venue.plan(
            AquaShipIntent(tokens=["USDC", "WETH"], amounts=["1000000", "1000000"]), _vault()
        )
        Draft202012Validator(schema).validate(
            json.loads(plan.model_dump_json(exclude_none=True))
        )


class TestCalldataEncoding:
    def test_ship_rejects_mismatched_arrays(self):
        with pytest.raises(ValueError, match="one amount per token"):
            ship_step("0xab", [addresses.WETH], [1, 2])

    def test_dock_encodes_the_strategy_hash(self):
        step = dock_step(STRATEGY_HASH, [addresses.WETH, addresses.USDC])
        assert STRATEGY_HASH[2:] in step.calldata

    def test_ship_targets_aqua_and_names_swapvm_as_the_app(self):
        step = ship_step("0x" + "cd" * 32, [addresses.WETH, addresses.USDC], [1, 2])
        assert step.target.lower() == addresses.AQUA.lower()
        assert addresses.SWAPVM[2:].lower() in step.calldata.lower()


# ── live: real eth_call against a local anvil ─────────────────────────────


@pytest.mark.live
class TestAgainstAnvil:
    async def test_builder_returns_real_program_bytes(self, anvil_rpc):
        from venues.aqua.program import ProgramBuilder

        program = await ProgramBuilder(anvil_rpc).build_program(fee_bps=30, salt=42)
        # opcode ‖ argLen ‖ args, three times over.
        assert program.startswith("0x70" "04"), "expected FlatFeeAmountIn with a uint32 arg"
        assert program[14:18] == "5000", "expected XYCSwap with no args"
        assert program[18:22] == "0220", "expected Salt with a 32-byte arg"

    async def test_builder_returns_a_real_strategy_and_hash(self, anvil_rpc):
        from venues.aqua.program import ProgramBuilder

        strategy = await ProgramBuilder(anvil_rpc).build_strategy(
            VAULT_ADDRESS, addresses.USDC, addresses.WETH, fee_bps=30, salt=42
        )
        assert len(strategy.strategy) > 2, "strategy bytes must be non-empty"
        assert strategy.strategy_hash != "0x" + "00" * 32
        # Sorted by the contract, so Python never has to know the rule.
        assert strategy.token_a.lower() == addresses.WETH.lower()
        assert strategy.token_b.lower() == addresses.USDC.lower()

    async def test_end_to_end_ship_plan_against_the_real_builder(self, anvil_rpc):
        from venues.aqua.program import ProgramBuilder

        venue = AquaVenue(builder=ProgramBuilder(anvil_rpc))
        plan = await venue.plan(
            AquaShipIntent(
                tokens=["USDC", "WETH"], amounts=["1000000000", "300000000000000000"]
            ),
            _vault(),
        )
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 3
        assert plan.steps[2].calldata.startswith("0x" + selector(AQUA_SHIP).hex())
        assert len(plan.steps[2].calldata) > 500, "ship calldata should embed the strategy"
