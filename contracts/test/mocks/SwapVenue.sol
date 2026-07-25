// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

import {IAggregatorV3} from "../../src/interfaces/IAggregatorV3.sol";
import {MockERC20} from "./MockERC20.sol";

/// @notice A venue that swaps at exactly the oracle price, with a configurable spread.
///
/// @dev Exists so the invariant suite can drive a *realistic* rebalance — the agent approving and
///      then swapping through `executeBatch` — rather than reaching in and rewriting the vault's
///      balances. That distinction matters: an invariant claiming "only `AGENT_ROLE` can move value"
///      proves nothing if the test moves value by fiat instead of by calling `execute`.
///
///      Pricing at the oracle means a swap is value-neutral by construction, so any drift in
///      `totalAssets()` across a rebalance is a real accounting bug rather than slippage noise. The
///      spread exists to model the loss case on purpose, not as an accident.
contract SwapVenue {
    using SafeERC20 for IERC20;

    MockERC20 public immutable usdc;
    MockERC20 public immutable weth;
    IAggregatorV3 public immutable feed;

    /// @notice Basis points taken out of every swap output. 0 = a perfectly fair swap.
    uint256 public spreadBps;

    constructor(MockERC20 usdc_, MockERC20 weth_, IAggregatorV3 feed_) {
        usdc = usdc_;
        weth = weth_;
        feed = feed_;
    }

    function setSpreadBps(uint256 bps) external {
        spreadBps = bps > 10_000 ? 10_000 : bps;
    }

    /// @notice USDC (6dp) in, WETH (18dp) out, priced by the 8dp feed.
    /// @dev `out = amountIn × 10^20 / price` — derived rather than tuned: amountIn/1e6 dollars,
    ///      divided by price/1e8 dollars-per-ETH, scaled to 1e18 wei.
    function swapUsdcForWeth(uint256 amountIn) external returns (uint256 out) {
        IERC20(address(usdc)).safeTransferFrom(msg.sender, address(this), amountIn);
        out = _applySpread((amountIn * 1e20) / _price());
        IERC20(address(weth)).safeTransfer(msg.sender, out);
    }

    /// @notice WETH in, USDC out. The exact inverse.
    function swapWethForUsdc(uint256 amountIn) external returns (uint256 out) {
        IERC20(address(weth)).safeTransferFrom(msg.sender, address(this), amountIn);
        out = _applySpread((amountIn * _price()) / 1e20);
        IERC20(address(usdc)).safeTransfer(msg.sender, out);
    }

    function _price() private view returns (uint256) {
        (, int256 answer,,,) = feed.latestRoundData();
        require(answer > 0, "SwapVenue: feed not reporting");
        // Safe: guarded by the require above.
        // forge-lint: disable-next-line(unsafe-typecast)
        return uint256(answer);
    }

    function _applySpread(uint256 amount) private view returns (uint256) {
        return (amount * (10_000 - spreadBps)) / 10_000;
    }
}
