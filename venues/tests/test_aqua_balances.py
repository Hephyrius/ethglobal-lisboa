"""Reading an Aqua position back — the assertion that makes R5 meaningful.

`ship()` succeeds with zero allowance and returns a valid strategy hash, so a
successful transaction proves only that the registry accepted some bytes.
`safeBalances()` is the only observable that distinguishes a fillable position
from an accounting entry (cross-lane request 17).
"""

from __future__ import annotations

import pytest

from venues import addresses
from venues.abi import selector
from venues.aqua.balances import (
    AQUA_SAFE_BALANCES,
    ERC20_ALLOWANCE,
    PositionBalances,
    assert_position_fillable,
    assert_position_live,
    read_position,
)

VAULT = "0x00000000000000000000000000000000000000A1"
STRATEGY_HASH = "0x" + "ab" * 32


class TestPositionBalances:
    def test_a_position_with_both_sides_funded_is_fillable(self):
        p = PositionBalances(addresses.WETH, addresses.USDC, 3 * 10**18, 10_000 * 10**6)
        assert p.live
        assert "fillable" in p.describe()

    @pytest.mark.parametrize(("a", "b"), [(0, 1), (1, 0), (0, 0)])
    def test_a_one_sided_or_empty_position_is_not_fillable(self, a, b):
        # A curve with nothing on one side cannot be traded against, so
        # reporting it as live would be exactly the false positive this module
        # exists to prevent.
        p = PositionBalances(addresses.WETH, addresses.USDC, a, b)
        assert not p.live
        assert "NOT fillable" in p.describe()


class _StubRpc:
    """Returns a canned eth_call result, capturing the calldata."""

    def __init__(self, result: str | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def eth_call(self, to: str, data: str, **_: object) -> str:
        self.calls.append((to, data))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _encoded(balance_a: int, balance_b: int) -> str:
    return "0x" + balance_a.to_bytes(32, "big").hex() + balance_b.to_bytes(32, "big").hex()


class TestReadPosition:
    async def test_it_calls_aqua_with_the_safe_balances_selector(self):
        rpc = _StubRpc(_encoded(1, 2))
        await read_position(
            rpc, maker=VAULT, strategy_hash=STRATEGY_HASH, token_a="WETH", token_b="USDC"
        )
        to, data = rpc.calls[0]
        assert to.lower() == addresses.AQUA.lower()
        assert data.startswith("0x" + selector(AQUA_SAFE_BALANCES).hex())
        # SwapVM is the "app" that may pull against the strategy.
        assert addresses.SWAPVM[2:].lower() in data.lower()

    async def test_it_resolves_token_symbols(self):
        rpc = _StubRpc(_encoded(1, 2))
        result = await read_position(
            rpc, maker=VAULT, strategy_hash=STRATEGY_HASH, token_a="WETH", token_b="USDC"
        )
        assert result is not None
        assert result.token_a == addresses.WETH
        assert result.token_b == addresses.USDC

    async def test_it_decodes_both_balances(self):
        rpc = _StubRpc(_encoded(3 * 10**18, 10_000 * 10**6))
        result = await read_position(
            rpc, maker=VAULT, strategy_hash=STRATEGY_HASH, token_a="WETH", token_b="USDC"
        )
        assert result is not None
        assert result.balance_a == 3 * 10**18
        assert result.balance_b == 10_000 * 10**6
        assert result.live

    async def test_a_revert_means_not_active_rather_than_an_error(self):
        """Aqua reverts for a docked or never-shipped strategy. That is an
        answer, not a failure — the caller needs `None`, not an exception."""
        from venues.rpc import RpcError

        rpc = _StubRpc(RpcError("eth_call", "execution reverted"))
        result = await read_position(
            rpc, maker=VAULT, strategy_hash=STRATEGY_HASH, token_a="WETH", token_b="USDC"
        )
        assert result is None

    async def test_a_truncated_response_is_not_read_as_zero_balances(self):
        # Decoding short data as zeros would report "shipped but empty" for
        # what is actually a broken call.
        rpc = _StubRpc("0x")
        assert (
            await read_position(
                rpc,
                maker=VAULT,
                strategy_hash=STRATEGY_HASH,
                token_a="WETH",
                token_b="USDC",
            )
            is None
        )


class _ScriptedRpc:
    """Answers `safeBalances` then two `allowance` calls, in that order."""

    def __init__(self, balances: str | Exception, allowances: tuple[int, int]) -> None:
        self.balances = balances
        self.allowances = allowances
        self.calls: list[tuple[str, str]] = []

    async def eth_call(self, to: str, data: str, **_: object) -> str:
        self.calls.append((to, data))
        if data.startswith("0x" + selector(AQUA_SAFE_BALANCES).hex()):
            if isinstance(self.balances, Exception):
                raise self.balances
            return self.balances
        # ERC-20 allowance, one per token in ship order.
        index = sum(
            1
            for _, d in self.calls[:-1]
            if d.startswith("0x" + selector(ERC20_ALLOWANCE).hex())
        )
        return "0x" + self.allowances[index].to_bytes(32, "big").hex()


SHIPPED = (3 * 10**18, 10_000 * 10**6)


class TestFillability:
    """Cross-lane request 39: balances alone would pass on a dead position."""

    async def test_the_exact_case_that_used_to_pass_now_fails(self):
        """**The regression this whole change exists for.** Perfect balances,
        valid hash, successful ship — and zero allowance, so every fill would
        revert. The old balances-only assertion called this healthy."""
        rpc = _ScriptedRpc(_encoded(*SHIPPED), allowances=(0, 0))
        with pytest.raises(AssertionError, match="NOT fillable"):
            await assert_position_fillable(
                rpc,
                maker=VAULT,
                strategy_hash=STRATEGY_HASH,
                token_a="WETH",
                token_b="USDC",
            )

    async def test_one_missing_approval_is_enough_to_kill_it(self):
        rpc = _ScriptedRpc(_encoded(*SHIPPED), allowances=(SHIPPED[0], 0))
        with pytest.raises(AssertionError, match="NOT fillable"):
            await assert_position_fillable(
                rpc,
                maker=VAULT,
                strategy_hash=STRATEGY_HASH,
                token_a="WETH",
                token_b="USDC",
            )

    async def test_a_fully_approved_position_passes(self):
        rpc = _ScriptedRpc(_encoded(*SHIPPED), allowances=SHIPPED)
        health = await assert_position_fillable(
            rpc, maker=VAULT, strategy_hash=STRATEGY_HASH, token_a="WETH", token_b="USDC"
        )
        assert health.fillable
        assert not health.dead

    async def test_an_allowance_below_the_shipped_amount_is_flagged(self):
        """Not dead, but smaller than it looks — a taker can be served up to the
        allowance and no further."""
        rpc = _ScriptedRpc(_encoded(*SHIPPED), allowances=(SHIPPED[0] // 2, SHIPPED[1]))
        with pytest.raises(AssertionError, match="partially fillable"):
            await assert_position_fillable(
                rpc,
                maker=VAULT,
                strategy_hash=STRATEGY_HASH,
                token_a="WETH",
                token_b="USDC",
            )

    async def test_it_reads_the_allowance_from_the_token_not_from_aqua(self):
        rpc = _ScriptedRpc(_encoded(*SHIPPED), allowances=SHIPPED)
        await assert_position_fillable(
            rpc, maker=VAULT, strategy_hash=STRATEGY_HASH, token_a="WETH", token_b="USDC"
        )
        allowance_calls = [
            (to, d)
            for to, d in rpc.calls
            if d.startswith("0x" + selector(ERC20_ALLOWANCE).hex())
        ]
        assert len(allowance_calls) == 2
        targets = {to.lower() for to, _ in allowance_calls}
        assert targets == {addresses.WETH.lower(), addresses.USDC.lower()}
        # spender must be Aqua — it is Aqua that pulls on fill, not SwapVM
        assert all(addresses.AQUA[2:].lower() in d.lower() for _, d in allowance_calls)

    async def test_no_active_strategy_names_the_likely_cause(self):
        from venues.rpc import RpcError

        rpc = _ScriptedRpc(RpcError("eth_call", "execution reverted"), allowances=(0, 0))
        with pytest.raises(AssertionError, match="no active strategy"):
            await assert_position_fillable(
                rpc,
                maker=VAULT,
                strategy_hash=STRATEGY_HASH,
                token_a="WETH",
                token_b="USDC",
            )

    async def test_an_empty_position_is_reported_differently_from_a_missing_one(self):
        """Shipped-but-empty, never-shipped and shipped-but-unapproved are three
        different bugs with three different fixes; they must not share a message."""
        rpc = _ScriptedRpc(_encoded(0, 0), allowances=(0, 0))
        with pytest.raises(AssertionError, match="nothing to trade against"):
            await assert_position_fillable(
                rpc,
                maker=VAULT,
                strategy_hash=STRATEGY_HASH,
                token_a="WETH",
                token_b="USDC",
            )

    async def test_the_old_name_now_performs_the_full_check(self):
        """`assert_position_live` was published to other lanes before request 39.
        Strengthening it beats leaving a weaker check behind a confident name."""
        rpc = _ScriptedRpc(_encoded(*SHIPPED), allowances=(0, 0))
        with pytest.raises(AssertionError, match="NOT fillable"):
            await assert_position_live(
                rpc,
                maker=VAULT,
                strategy_hash=STRATEGY_HASH,
                token_a="WETH",
                token_b="USDC",
            )


@pytest.mark.live
class TestAgainstRealAqua:
    async def test_an_unknown_strategy_reads_as_not_active(self, anvil_rpc):
        """Against the real deployed Aqua: a hash nobody shipped must come back
        as `None`, not as a spurious zero-balance position."""
        result = await read_position(
            anvil_rpc,
            maker=VAULT,
            strategy_hash="0x" + "cd" * 32,
            token_a="WETH",
            token_b="USDC",
        )
        assert result is None
