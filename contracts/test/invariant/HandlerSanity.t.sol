// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {CuratedVault} from "../../src/CuratedVault.sol";
import {VaultFactory} from "../../src/VaultFactory.sol";
import {IAggregatorV3} from "../../src/interfaces/IAggregatorV3.sol";
import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";
import {IVaultFactory} from "../../src/interfaces/IVaultFactory.sol";
import {MockAggregatorV3} from "../mocks/MockAggregatorV3.sol";
import {MockERC20} from "../mocks/MockERC20.sol";
import {SwapVenue} from "../mocks/SwapVenue.sol";
import {VaultHandler} from "./VaultHandler.sol";

/// @notice Proves the handler's actions actually do something.
///
/// @dev The failure mode this exists for is specific and nasty: a handler action that silently
///      becomes a no-op — a bound that can never be satisfied, a `try` swallowing a revert — turns
///      the whole invariant campaign into a green run over a vault nothing happened to. Every
///      property still passes, and it proves nothing.
///
///      `afterInvariant` catches it at the campaign level; this catches it here, where the failure
///      names the individual action instead of the aggregate.
contract HandlerSanityTest is Test {
    MockERC20 internal usdc;
    MockERC20 internal weth;
    MockAggregatorV3 internal feed;
    SwapVenue internal venue;
    VaultFactory internal factory;
    CuratedVault internal vault;
    VaultHandler internal handler;

    address internal platform = makeAddr("platform");
    address internal agent = makeAddr("agent");
    address internal guardian = makeAddr("guardian");

    function setUp() public {
        vm.warp(1_700_000_000);

        usdc = new MockERC20("USD Coin", "USDC", 6);
        weth = new MockERC20("Wrapped Ether", "WETH", 18);
        feed = new MockAggregatorV3(8, "ETH / USD", 3000e8);
        venue = new SwapVenue(usdc, weth, IAggregatorV3(address(feed)));

        usdc.mint(address(venue), 1_000_000_000e6);
        weth.mint(address(venue), 1_000_000e18);

        address[] memory targets = new address[](3);
        targets[0] = address(venue);
        targets[1] = address(usdc);
        targets[2] = address(weth);

        ICuratedVault.TokenValuation[] memory valuations = new ICuratedVault.TokenValuation[](1);
        valuations[0] = ICuratedVault.TokenValuation({token: address(weth), feed: address(feed)});

        factory = new VaultFactory(platform, targets, valuations, 0);
        vault = CuratedVault(
            factory.createVault(
                IVaultFactory.CreateParams({
                    asset: address(usdc),
                    name: "Curated USDC",
                    symbol: "cUSDC",
                    agent: agent,
                    guardian: guardian,
                    mandateHash: keccak256("sanity")
                })
            )
        );

        address[] memory actors = new address[](2);
        actors[0] = makeAddr("alice");
        actors[1] = makeAddr("bob");

        handler = new VaultHandler(vault, usdc, weth, feed, venue, agent, guardian, actors);
    }

    function test_depositActionActuallyDeposits() public {
        handler.deposit(1_000e6, 0);

        assertEq(handler.depositCount(), 1, "deposit did not register");
        assertGt(vault.totalAssets(), 0, "no assets reached the vault");
        assertGt(vault.balanceOf(handler.actorAt(0)), 0, "the actor holds no shares");
    }

    function test_redeemActionActuallyRedeems() public {
        handler.deposit(1_000e6, 0);
        uint256 sharesBefore = vault.balanceOf(handler.actorAt(0));

        handler.redeem(type(uint256).max, 0); // seed bounds to the full holding

        assertEq(handler.withdrawCount(), 1, "redeem did not register");
        assertLt(vault.balanceOf(handler.actorAt(0)), sharesBefore, "no shares were burned");
        assertGt(handler.totalWithdrawn(), 0, "no assets came back");
    }

    function test_agentSwapActionActuallySwaps() public {
        handler.deposit(10_000e6, 0);

        handler.agentSwapUsdcForWeth(5_000e6);

        assertEq(handler.agentSwapCount(), 1, "swap did not register");
        assertGt(weth.balanceOf(address(vault)), 0, "the vault holds no WETH");
        assertLt(usdc.balanceOf(address(vault)), 10_000e6, "no USDC was spent");
    }

    /// @dev A fair swap at the oracle price is value-neutral, so this doubles as a check that the
    ///      valuation path and the swap price agree. Drift here would mean a rebalance silently
    ///      creates or destroys value on paper.
    function test_agentSwapIsValueNeutral() public {
        handler.deposit(10_000e6, 0);
        uint256 before = vault.totalAssets();

        handler.agentSwapUsdcForWeth(5_000e6);

        assertApproxEqAbs(vault.totalAssets(), before, 2, "a fair swap changed the book's value");
    }

    function test_swapBackAndForthLosesOnlyRounding() public {
        handler.deposit(10_000e6, 0);
        uint256 before = vault.totalAssets();

        handler.agentSwapUsdcForWeth(5_000e6);
        handler.agentSwapWethForUsdc(type(uint256).max);

        assertApproxEqAbs(vault.totalAssets(), before, 2, "a round trip lost value");
    }

    /// @dev Each attack must be reachable *and* fail. If an attack silently no-ops, the counter it
    ///      guards stays zero for the wrong reason and the invariant passes vacuously.
    function test_attacksAreExercisedAndAllFail() public {
        handler.deposit(1_000e6, 0);

        handler.attackUnauthorizedExecute(0, 0, hex"");
        handler.attackGuardianSpends(hex"");
        handler.attackNonAllowlistedTarget(makeAddr("stranger"), hex"");
        handler.attackRoleChange(0);
        handler.attackReinitialize(makeAddr("attacker"));

        assertEq(handler.unauthorizedValueMoves(), 0, "a non-agent moved value");
        assertEq(handler.nonAllowlistedTargetsReached(), 0, "reached a target off the allowlist");
        assertEq(handler.roleChangesAccepted(), 0, "a role change was accepted");
        assertEq(handler.reinitializations(), 0, "the vault was re-initialized");
    }
}
