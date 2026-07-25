// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ReentrancyGuardUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";

import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";
import {CallTarget} from "../mocks/CallTarget.sol";
import {VaultTestBase} from "./VaultTestBase.sol";

/// @notice The agent's execution surface — the seam Lane D builds calldata against, and the one
///         place arbitrary code runs on the vault's behalf.
contract CuratedVaultExecuteTest is VaultTestBase {
    function test_agentCanCallAnAllowlistedTarget() public {
        vm.prank(agent);
        bytes memory ret = vault.execute(address(venue), 0, abi.encodeCall(CallTarget.ping, (21)));

        assertEq(abi.decode(ret, (uint256)), 42, "return data comes back to the caller");
        assertEq(venue.callCount(), 1, "the venue saw the call");
    }

    function test_executeEmitsWithTheSelectorIndexed() public {
        vm.expectEmit(true, true, false, true, address(vault));
        emit ICuratedVault.Executed(address(venue), CallTarget.ping.selector, 0);

        vm.prank(agent);
        vault.execute(address(venue), 0, abi.encodeCall(CallTarget.ping, (1)));
    }

    function test_onlyAgentMayExecute() public {
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, alice, vault.AGENT_ROLE())
        );
        vm.prank(alice);
        vault.execute(address(venue), 0, abi.encodeCall(CallTarget.ping, (1)));
    }

    /// @dev Even the guardian, who controls the allowlist, cannot move a single token.
    function test_guardianMayNotExecute() public {
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, guardian, vault.AGENT_ROLE()
            )
        );
        vm.prank(guardian);
        vault.execute(address(venue), 0, abi.encodeCall(CallTarget.ping, (1)));
    }

    function test_targetMustBeAllowlisted() public {
        address stranger = makeAddr("unknownVenue");

        vm.expectRevert(abi.encodeWithSelector(ICuratedVault.TargetNotAllowed.selector, stranger));
        vm.prank(agent);
        vault.execute(stranger, 0, abi.encodeCall(CallTarget.ping, (1)));
    }

    /// @dev Lane D cross-lane request #8: an `ExecutionPlan` step for `USDC.approve(Permit2, …)`
    ///      targets the *token*, not a venue. Tokens are on the allowlist, so the golden fixture's
    ///      shape works unchanged.
    function test_tokenAddressesWorkAsExecuteTargets() public {
        _deposit(alice, 1_000e6);

        vm.prank(agent);
        vault.execute(address(usdc), 0, abi.encodeCall(IERC20.approve, (address(venue), 500e6)));

        assertEq(usdc.allowance(address(vault), address(venue)), 500e6, "approval landed");
    }

    function test_valueIsForwarded() public {
        // The vault has no receive(), so it can never accrue ETH on its own. Forcing a balance is
        // the only way to exercise the value path — and confirms it works if a vault is ever funded.
        vm.deal(address(vault), 1 ether);

        vm.prank(agent);
        vault.execute(address(venue), 0.5 ether, abi.encodeCall(CallTarget.ping, (1)));

        assertEq(venue.lastValue(), 0.5 ether, "value reached the venue");
        assertEq(address(vault).balance, 0.5 ether, "and left the vault");
    }

    // ── batching ─────────────────────────────────────────────────────────

    function test_batchAppliesEveryStepInOrder() public {
        _deposit(alice, 1_000e6);

        ICuratedVault.Call[] memory calls = new ICuratedVault.Call[](2);
        calls[0] = ICuratedVault.Call({
            target: address(usdc),
            value: 0,
            data: abi.encodeCall(IERC20.approve, (address(venue), 1_000e6))
        });
        calls[1] =
            ICuratedVault.Call({target: address(venue), value: 0, data: abi.encodeCall(CallTarget.ping, (7))});

        vm.prank(agent);
        bytes[] memory results = vault.executeBatch(calls);

        assertEq(usdc.allowance(address(vault), address(venue)), 1_000e6, "step 1: approval");
        assertEq(abi.decode(results[1], (uint256)), 14, "step 2: return data, in order");
    }

    /// @dev The reason batching exists: a plan is ordered and must not land half-applied.
    function test_batchIsAtomic() public {
        _deposit(alice, 1_000e6);

        ICuratedVault.Call[] memory calls = new ICuratedVault.Call[](2);
        calls[0] = ICuratedVault.Call({
            target: address(usdc),
            value: 0,
            data: abi.encodeCall(IERC20.approve, (address(venue), 1_000e6))
        });
        calls[1] = ICuratedVault.Call({
            target: address(venue),
            value: 0,
            data: abi.encodeCall(CallTarget.revertWithReason, ())
        });

        vm.expectRevert("venue said no");
        vm.prank(agent);
        vault.executeBatch(calls);

        assertEq(usdc.allowance(address(vault), address(venue)), 0, "step 1 was rolled back with step 2");
    }

    function test_emptyBatchReverts() public {
        vm.expectRevert(ICuratedVault.EmptyBatch.selector);
        vm.prank(agent);
        vault.executeBatch(new ICuratedVault.Call[](0));
    }

    // ── revert propagation ───────────────────────────────────────────────

    function test_bubblesCustomErrors() public {
        vm.expectRevert(abi.encodeWithSelector(CallTarget.Boom.selector, 42));
        vm.prank(agent);
        vault.execute(address(venue), 0, abi.encodeCall(CallTarget.revertWithCustomError, ()));
    }

    function test_bubblesStringReasons() public {
        vm.expectRevert("venue said no");
        vm.prank(agent);
        vault.execute(address(venue), 0, abi.encodeCall(CallTarget.revertWithReason, ()));
    }

    function test_silentRevertStillFails() public {
        vm.expectRevert();
        vm.prank(agent);
        vault.execute(address(venue), 0, abi.encodeCall(CallTarget.revertSilently, ()));
    }

    // ── reentrancy ───────────────────────────────────────────────────────

    /// @dev Two independent barriers stop this, and the role check is the one that fires: on
    ///      re-entry `msg.sender` is the venue, not the agent, so it never reaches the guard.
    ///      Asserted as access control rather than reentrancy because that is what actually
    ///      protects the vault here — the guard is the backstop for the *permissionless* entry
    ///      points, which is what the next test covers.
    function test_venueCannotReenterExecute() public {
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, address(venue), vault.AGENT_ROLE()
            )
        );
        vm.prank(agent);
        vault.execute(
            address(venue), 0, abi.encodeCall(CallTarget.reenterExecute, (address(vault), address(venue)))
        );
    }

    /// @dev The attack the guard is really for: re-enter `deposit` mid-rebalance, after the vault
    ///      has spent USDC but before it has received the token it bought, and mint shares against
    ///      an understated `totalAssets()`.
    function test_venueCannotReenterDeposit() public {
        _deposit(alice, 1_000e6);
        usdc.mint(address(venue), 100e6);

        vm.expectRevert(ReentrancyGuardUpgradeable.ReentrancyGuardReentrantCall.selector);
        vm.prank(agent);
        vault.execute(
            address(venue), 0, abi.encodeCall(CallTarget.reenterDeposit, (address(vault), 1e6, address(venue)))
        );
    }

    // ── approveVenue ─────────────────────────────────────────────────────

    function test_approveVenueSetsAllowance() public {
        vm.prank(agent);
        vault.approveVenue(address(usdc), address(venue), 500e6);

        assertEq(usdc.allowance(address(vault), address(venue)), 500e6, "allowance");
    }

    /// @dev forceApprove, not approve: re-approving a non-zero allowance to a different non-zero
    ///      value is rejected outright by USDT-family tokens.
    function test_approveVenueCanChangeANonZeroAllowance() public {
        vm.startPrank(agent);
        vault.approveVenue(address(usdc), address(venue), 500e6);
        vault.approveVenue(address(usdc), address(venue), 900e6);
        vm.stopPrank();

        assertEq(usdc.allowance(address(vault), address(venue)), 900e6, "second approval took effect");
    }

    function test_approveVenueRejectsAnUnknownSpender() public {
        address stranger = makeAddr("unknownSpender");

        vm.expectRevert(abi.encodeWithSelector(ICuratedVault.SpenderNotAllowed.selector, stranger));
        vm.prank(agent);
        vault.approveVenue(address(usdc), stranger, 1);
    }

    function test_onlyAgentMayApprove() public {
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, alice, vault.AGENT_ROLE())
        );
        vm.prank(alice);
        vault.approveVenue(address(usdc), address(venue), 1);
    }
}
