// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";

/// @notice A stand-in for a venue, used to prove what `execute` does with a call.
/// @dev Records what it received, can be told to revert in each of the three ways a real venue can
///      (custom error, string reason, silent), and can attempt to re-enter the vault.
contract CallTarget {
    error Boom(uint256 code);

    uint256 public lastValue;
    bytes public lastData;
    uint256 public callCount;

    function ping(uint256 x) external payable returns (uint256) {
        lastValue = msg.value;
        lastData = msg.data;
        callCount++;
        return x * 2;
    }

    function revertWithCustomError() external pure {
        revert Boom(42);
    }

    function revertWithReason() external pure {
        revert("venue said no");
    }

    /// @dev No revert data at all — the case where a naive `execute` would surface nothing useful.
    function revertSilently() external pure {
        assembly {
            revert(0, 0)
        }
    }

    /// @notice Try to re-enter the vault mid-execution. Must be stopped by the reentrancy guard.
    function reenterExecute(address vault, address target) external {
        ICuratedVault(vault).execute(target, 0, abi.encodeCall(CallTarget.ping, (1)));
    }

    /// @notice Try to deposit into the vault while it is mid-rebalance.
    function reenterDeposit(address vault, uint256 assets, address receiver) external {
        (bool ok, bytes memory ret) =
            vault.call(abi.encodeWithSignature("deposit(uint256,address)", assets, receiver));
        if (!ok) {
            assembly {
                revert(add(ret, 0x20), mload(ret))
            }
        }
    }
}
