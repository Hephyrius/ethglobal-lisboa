// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @notice A venue that moves exactly the tokens you name, in exactly the amounts you name.
///
/// @dev Deliberately dumber than `SwapVenue`, which prices off the oracle so a rebalance is
///      value-neutral by construction. The wind-down rule does not care what anything is worth — it
///      reads balances — so what its tests need is *arbitrary* control over which balance moves
///      which way, including combinations no honest market would produce.
///
///      Four shapes fall out of one function, which is why there is only one:
///
///      | Call | Shape |
///      |---|---|
///      | `swap(weth, 1e18, usdc, 3000e6)` | an ordinary sale — the thing wind-down exists to permit |
///      | `swap(usdc, 3000e6, weth, 1e18)` | a purchase — the thing wind-down exists to forbid |
///      | `swap(weth, 0, weth, 1e18)` | a gift, e.g. a reward claim: a holding rises, cash does not fall |
///      | `swap(weth, 2e18, usdc, 1)` | a sale at a catastrophic price — permitted, and that is the point |
///
///      Fund it with `mint` before asking it for anything; it holds no inventory of its own.
contract WindDownVenue {
    using SafeERC20 for IERC20;

    function swap(address tokenIn, uint256 amountIn, address tokenOut, uint256 amountOut) external {
        // Zero legs are skipped rather than transferred: a zero-amount transfer is legal ERC-20 but
        // not universally accepted, and the gift and burn shapes above both need one leg empty.
        if (amountIn != 0) IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        if (amountOut != 0) IERC20(tokenOut).safeTransfer(msg.sender, amountOut);
    }
}
