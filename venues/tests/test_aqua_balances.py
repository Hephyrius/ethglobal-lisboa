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
    PositionBalances,
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


class TestAssertPositionLive:
    async def test_it_returns_the_balances_when_the_position_is_real(self):
        rpc = _StubRpc(_encoded(3 * 10**18, 10_000 * 10**6))
        balances = await assert_position_live(
            rpc, maker=VAULT, strategy_hash=STRATEGY_HASH, token_a="WETH", token_b="USDC"
        )
        assert balances.live

    async def test_no_active_strategy_names_the_likely_cause(self):
        from venues.rpc import RpcError

        rpc = _StubRpc(RpcError("eth_call", "execution reverted"))
        with pytest.raises(AssertionError, match="no active strategy"):
            await assert_position_live(
                rpc,
                maker=VAULT,
                strategy_hash=STRATEGY_HASH,
                token_a="WETH",
                token_b="USDC",
            )

    async def test_an_empty_position_is_reported_differently_from_a_missing_one(self):
        """Shipped-but-empty and never-shipped are different bugs with
        different fixes, so they must not share a message."""
        rpc = _StubRpc(_encoded(0, 0))
        with pytest.raises(AssertionError, match="nothing can fill it"):
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
