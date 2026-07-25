// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";

import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";
import {CallTarget} from "../mocks/CallTarget.sol";
import {VaultTestBase} from "./VaultTestBase.sol";

/// @notice The trust model, asserted.
///
/// @dev The locked decision is that no human can override the agent after genesis
///      (`plans/initiate_plan.md` §2). These tests are what stop that from quietly eroding into
///      "there is an admin key, we just do not use it".
contract CuratedVaultRolesTest is VaultTestBase {
    bytes32 internal constant DEFAULT_ADMIN_ROLE = 0x00;

    function test_rolesAreAssignedAtGenesis() public view {
        assertTrue(vault.hasRole(vault.AGENT_ROLE(), agent), "agent holds AGENT_ROLE");
        assertTrue(vault.hasRole(vault.GUARDIAN_ROLE(), guardian), "guardian holds GUARDIAN_ROLE");
    }

    /// @dev The single most important assertion in this file. If anyone held the admin role they
    ///      could grant themselves AGENT_ROLE and take the money.
    function test_nobodyHoldsTheAdminRole() public view {
        assertFalse(vault.hasRole(DEFAULT_ADMIN_ROLE, platform), "platform");
        assertFalse(vault.hasRole(DEFAULT_ADMIN_ROLE, address(factory)), "factory");
        assertFalse(vault.hasRole(DEFAULT_ADMIN_ROLE, agent), "agent");
        assertFalse(vault.hasRole(DEFAULT_ADMIN_ROLE, guardian), "guardian");
        assertFalse(vault.hasRole(DEFAULT_ADMIN_ROLE, address(this)), "deployer");
    }

    function test_grantIsUnreachableForEveryone() public {
        // Hoisted deliberately: `vault.AGENT_ROLE()` is itself an external call, and left inline it
        // would be the call `vm.expectRevert` matched against, so the assertion would pass without
        // ever testing grantRole.
        bytes32 agentRole = vault.AGENT_ROLE();

        address[4] memory who = [agent, guardian, platform, alice];
        for (uint256 i; i < who.length; ++i) {
            vm.expectRevert(ICuratedVault.RolesAreFrozen.selector);
            vm.prank(who[i]);
            vault.grantRole(agentRole, alice);
        }
    }

    function test_revokeIsUnreachableForEveryone() public {
        bytes32 agentRole = vault.AGENT_ROLE();

        address[4] memory who = [agent, guardian, platform, alice];
        for (uint256 i; i < who.length; ++i) {
            vm.expectRevert(ICuratedVault.RolesAreFrozen.selector);
            vm.prank(who[i]);
            vault.revokeRole(agentRole, agent);
        }
    }

    /// @dev Renouncing is the one AccessControl path a role holder can always walk by default.
    ///      Left open, the agent could brick the vault it curates — capital locked, nobody able to
    ///      rebalance, depositors still able to withdraw but into a frozen strategy.
    function test_agentCannotRenounceAndBrickTheVault() public {
        bytes32 agentRole = vault.AGENT_ROLE();

        vm.expectRevert(ICuratedVault.RolesAreFrozen.selector);
        vm.prank(agent);
        vault.renounceRole(agentRole, agent);

        assertTrue(vault.hasRole(agentRole, agent), "agent is still the curator");
    }

    // ── the guardian's one power ─────────────────────────────────────────

    function test_guardianCanWidenTheAllowlist() public {
        address newVenue = makeAddr("newVenue");
        assertFalse(vault.isAllowedTarget(newVenue), "not allowed yet");

        vm.expectEmit(true, false, false, true, address(vault));
        emit ICuratedVault.TargetAllowed(newVenue, true);

        vm.prank(guardian);
        vault.setTargetAllowed(newVenue, true);

        assertTrue(vault.isAllowedTarget(newVenue), "now allowed");
    }

    function test_guardianCanNarrowTheAllowlist() public {
        vm.prank(guardian);
        vault.setTargetAllowed(address(venue), false);

        assertFalse(vault.isAllowedTarget(address(venue)), "removed");

        vm.expectRevert(abi.encodeWithSelector(ICuratedVault.TargetNotAllowed.selector, address(venue)));
        vm.prank(agent);
        vault.execute(address(venue), 0, abi.encodeCall(CallTarget.ping, (1)));
    }

    function test_onlyGuardianMayEditTheAllowlist() public {
        address[3] memory who = [agent, platform, alice];
        for (uint256 i; i < who.length; ++i) {
            vm.expectRevert(
                abi.encodeWithSelector(
                    IAccessControl.AccessControlUnauthorizedAccount.selector, who[i], vault.GUARDIAN_ROLE()
                )
            );
            vm.prank(who[i]);
            vault.setTargetAllowed(makeAddr("x"), true);
        }
    }

    /// @dev Widening the allowlist must not become a way to reach the money. Only AGENT_ROLE can
    ///      call `execute`, so the guardian adding a target it controls still gets it nothing.
    function test_guardianGainsNoSpendingPowerByWidening() public {
        _deposit(alice, 1_000e6);
        address guardiansOwnContract = makeAddr("guardiansContract");

        vm.prank(guardian);
        vault.setTargetAllowed(guardiansOwnContract, true);

        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, guardian, vault.AGENT_ROLE()
            )
        );
        vm.prank(guardian);
        vault.execute(guardiansOwnContract, 0, "");

        assertEq(usdc.balanceOf(address(vault)), 1_000e6, "not a wei moved");
    }

    /// @dev Valuation is where a mutable setting *would* be exploitable — a bogus feed reprices
    ///      every share. So there is deliberately no setter at all, for anyone.
    function test_thereIsNoWayToChangeValuation() public view {
        assertEq(vault.priceFeed(address(weth)), address(ethFeed), "feed fixed at genesis");
        assertEq(vault.valuedTokens().length, 1, "valuation set fixed at genesis");
    }

    function test_initializeCannotBeCalledTwice() public {
        ICuratedVault.InitParams memory p = ICuratedVault.InitParams({
            asset: address(usdc),
            name: "Hijacked",
            symbol: "HAX",
            agent: alice,
            guardian: alice,
            mandateHash: bytes32(0),
            allowedTargets: new address[](0),
            valuations: new ICuratedVault.TokenValuation[](0),
            priceMaxAge: 0
        });

        vm.expectRevert(); // InvalidInitialization
        vm.prank(alice);
        vault.initialize(p);
    }

    /// @dev The implementation the clones delegate to must not be initializable either, or someone
    ///      could pose as a vault at a well-known address.
    function test_implementationIsLocked() public {
        ICuratedVault.InitParams memory p = ICuratedVault.InitParams({
            asset: address(usdc),
            name: "Impl",
            symbol: "IMPL",
            agent: alice,
            guardian: alice,
            mandateHash: bytes32(0),
            allowedTargets: new address[](0),
            valuations: new ICuratedVault.TokenValuation[](0),
            priceMaxAge: 0
        });

        address impl = factory.implementation();

        vm.expectRevert(); // InvalidInitialization — _disableInitializers() in the constructor
        vm.prank(alice);
        ICuratedVault(impl).initialize(p);
    }
}
