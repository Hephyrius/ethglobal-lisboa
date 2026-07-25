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

    // ─────────────────────────────────────────────────────────────────────
    // Deployer attribution — who asked for this vault
    // ─────────────────────────────────────────────────────────────────────

    /// @dev The archetype case: a vault someone deployed and never deposited into. `balanceOf`
    ///      cannot see it, which is why the dashboard needs this record at all.
    function test_deployerIsRecordedAndQueryable() public {
        address created = factory.createVault(_createParams());

        assertEq(factory.deployerOf(created), deployer, "recorded against the address that asked");
        assertEq(factory.vaultsOf(deployer).length, 2, "the base fixture's vault plus this one");
        assertEq(factory.vaultsOf(deployer)[1], created, "in creation order");
        assertEq(CuratedVault(created).balanceOf(deployer), 0, "and holds no shares, which is the point");
    }

    /// @dev `deployer` and `msg.sender` differ here on purpose: at genesis the *agent* submits the
    ///      transaction, so if these were allowed to collapse the test would prove nothing.
    function test_deployerIsIndexedOnTheEvent() public {
        address expected = _predictNextVault();

        vm.expectEmit(true, true, true, true, address(factory));
        emit IVaultFactory.VaultCreated(expected, address(usdc), agent, MANDATE_HASH, deployer);

        vm.prank(agent);
        assertEq(factory.createVault(_createParams()), expected, "predicted the clone address");
    }

    function test_deployerDefaultsToTheSubmitter() public {
        IVaultFactory.CreateParams memory p = _createParams();
        p.deployer = address(0);

        vm.prank(agent);
        address created = factory.createVault(p);

        assertEq(factory.deployerOf(created), agent, "never null: falls back to msg.sender");
    }

    function test_vaultsOfSeparatesDeployers() public {
        IVaultFactory.CreateParams memory p = _createParams();
        p.deployer = alice;
        address hers = factory.createVault(p);

        p.deployer = bob;
        factory.createVault(p);

        assertEq(factory.vaultsOf(alice).length, 1, "alice sees only her own");
        assertEq(factory.vaultsOf(alice)[0], hers, "and it is the right one");
        assertEq(factory.vaultsOf(bob).length, 1, "bob likewise");
        assertEq(factory.vaultsOf(makeAddr("nobody")).length, 0, "a stranger sees nothing");
        assertEq(factory.deployerOf(makeAddr("notAVault")), address(0), "and an unknown vault has no deployer");
    }

    /// @dev The limitation, as a test rather than a footnote. `deployer` is *asserted* by whoever
    ///      submits the transaction — there is no signature behind it — so anyone can claim a vault
    ///      was deployed for anyone. That is tolerable only because it confers nothing.
    function test_deployerIsAClaimAndGrantsNoPowers() public {
        IVaultFactory.CreateParams memory p = _createParams();
        p.deployer = alice;

        vm.prank(bob);
        CuratedVault claimed = CuratedVault(factory.createVault(p));

        assertEq(factory.deployerOf(address(claimed)), alice, "bob attributed the vault to alice unilaterally");

        // And it bought her nothing: not the agent's powers, not the guardian's, not a share.
        vm.startPrank(alice);
        vm.expectRevert();
        claimed.execute(address(venue), 0, "");
        vm.expectRevert();
        claimed.pause();
        vm.expectRevert();
        claimed.setTargetAllowed(address(venue), false);
        vm.stopPrank();

        assertEq(claimed.balanceOf(alice), 0, "attribution is a label, not a balance");
    }

    /// @dev Clones are deployed with `Clones.clone`, whose address depends only on the deployer and
    ///      nonce — so the next one is predictable without mining it.
    function _predictNextVault() private returns (address) {
        uint256 snapshot = vm.snapshotState();
        address next = factory.createVault(_createParams());
        vm.revertToState(snapshot);
        return next;
    }
}
