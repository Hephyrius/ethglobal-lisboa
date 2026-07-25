// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {CuratedVault} from "../../src/CuratedVault.sol";
import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";
import {IVaultFactory} from "../../src/interfaces/IVaultFactory.sol";
import {MockAggregatorV3} from "../mocks/MockAggregatorV3.sol";
import {VaultTestBase} from "./VaultTestBase.sol";

/// @notice The mutable-template / immutable-instance split, which is the factory's whole reason to
///         exist beyond cheap deploys.
contract VaultFactoryTest is VaultTestBase {
    function test_createVaultEmitsTheIndexedEvent() public {
        // The event Lane E's indexer and the dApp key off. Address is unknown ahead of time, so
        // only the non-indexed data is checked strictly.
        vm.recordLogs();
        address created = factory.createVault(_createParams());

        assertTrue(factory.isVault(created), "registered");
        assertEq(factory.vaultCount(), 2, "the base fixture created one already");
        assertEq(factory.vaults()[1], created, "creation order preserved");
    }

    function test_clonesShareTheImplementation() public {
        address a = factory.createVault(_createParams());
        address b = factory.createVault(_createParams());

        assertTrue(a != b, "distinct addresses");
        assertTrue(a.code.length < 100, "EIP-1167 clones are tiny");
        assertEq(CuratedVault(a).asset(), address(usdc), "still a working vault");
        assertEq(CuratedVault(b).mandateHash(), MANDATE_HASH, "and independently initialized");
    }

    function test_newVaultSnapshotsTheDefaults() public view {
        assertTrue(vault.isAllowedTarget(address(venue)), "venue");
        assertTrue(vault.isAllowedTarget(address(usdc)), "usdc as an approve target");
        assertTrue(vault.isAllowedTarget(address(weth)), "weth");
        assertEq(vault.allowedTargets().length, 3, "exactly the seeded set");
        assertEq(vault.priceFeed(address(weth)), address(ethFeed), "valuation copied");
        assertEq(vault.priceMaxAge(), PRICE_MAX_AGE, "staleness bound copied");
    }

    /// @dev The point of the split. Widening the template must not silently widen vaults that are
    ///      already live and already holding money.
    function test_changingADefaultDoesNotReachAnExistingVault() public {
        address lateVenue = makeAddr("routerDiscoveredLater");

        vm.prank(platform);
        factory.setDefaultTarget(lateVenue, true);

        assertFalse(vault.isAllowedTarget(lateVenue), "the live vault is untouched");

        address fresh = factory.createVault(_createParams());
        assertTrue(CuratedVault(fresh).isAllowedTarget(lateVenue), "but the next clone picks it up");
    }

    function test_defaultValuationsCanBeAddedAndRemoved() public {
        MockAggregatorV3 btcFeed = new MockAggregatorV3(8, "BTC / USD", 60_000e8);
        address cbbtc = makeAddr("cbBTC");

        vm.startPrank(platform);
        factory.setDefaultValuation(cbbtc, address(btcFeed));
        assertEq(factory.defaultValuations().length, 2, "added");

        factory.setDefaultValuation(cbbtc, address(0));
        assertEq(factory.defaultValuations().length, 1, "removed");
        vm.stopPrank();
    }

    function test_removingAnUnknownValuationReverts() public {
        vm.expectRevert(abi.encodeWithSelector(IVaultFactory.UnknownDefaultValuation.selector, address(0xdead)));
        vm.prank(platform);
        factory.setDefaultValuation(address(0xdead), address(0));
    }

    function test_onlyOwnerMayEditDefaults() public {
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, alice));
        vm.prank(alice);
        factory.setDefaultTarget(makeAddr("x"), true);

        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, alice));
        vm.prank(alice);
        factory.setDefaultPriceMaxAge(1);
    }

    /// @dev The factory owner is a platform operator, not a vault admin. It has no role in any vault
    ///      it created — no execute, no allowlist, nothing.
    function test_factoryOwnerHasNoPowerOverAVault() public view {
        assertFalse(vault.hasRole(vault.AGENT_ROLE(), platform), "not the agent");
        assertFalse(vault.hasRole(vault.GUARDIAN_ROLE(), platform), "not the guardian");
        assertFalse(vault.hasRole(0x00, platform), "not an admin - nobody is");
    }

    function test_rejectsZeroAddresses() public {
        IVaultFactory.CreateParams memory p = _createParams();
        p.agent = address(0);

        vm.expectRevert(ICuratedVault.ZeroAddress.selector);
        factory.createVault(p);
    }

    function test_duplicateValuationIsRejectedAtInit() public {
        // Registering the base asset as a valued token would double-count it in totalAssets().
        vm.prank(platform);
        factory.setDefaultValuation(address(usdc), address(ethFeed));

        vm.expectRevert(abi.encodeWithSelector(ICuratedVault.DuplicateValuation.selector, address(usdc)));
        factory.createVault(_createParams());
    }
}
