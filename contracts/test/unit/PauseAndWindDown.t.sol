// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";

import {CuratedVault} from "../../src/CuratedVault.sol";
import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";

import {CallTarget} from "../mocks/CallTarget.sol";
import {MockAggregatorV3} from "../mocks/MockAggregatorV3.sol";
import {MockERC20} from "../mocks/MockERC20.sol";
import {WindDownVenue} from "../mocks/WindDownVenue.sol";
import {VaultTestBase} from "./VaultTestBase.sol";

/// @notice The guardian's pause, the wind-down rule it turns on, and the in-kind exit that makes
///         being trapped impossible.
///
/// @dev Most of this file is security properties written as assertions, so read the test names as
///      claims. Three of them are the load-bearing ones:
///
///      - `test_withdrawalSucceedsWhilePaused` — a guardian who could freeze exits would hold
///        strictly more power than the agent it exists to contain. This is the boundary.
///      - `test_windDownRefusesToIncreaseAHolding` — while paused, even a fully compromised agent
///        key can only convert the book to cash.
///      - `test_redeemInKindClosesTheBookSection10CouldNotPay` — the exact position `SECURITY.md`
///        §10 measured and declined to fix, now paid out in full.
contract PauseAndWindDownTest is VaultTestBase {
    MockERC20 internal cbeth;
    MockAggregatorV3 internal cbethFeed;
    WindDownVenue internal market;

    int256 internal constant CBETH_USD = 3_200e8;

    /// @dev A second registered holding, because the multi-hop test needs a token the vault can
    ///      *transiently* hold and the rule can see. With only WETH registered, an intermediate leg
    ///      would be invisible and the test would pass without proving anything.
    function setUp() public override {
        super.setUp();

        cbeth = new MockERC20("Coinbase Wrapped Staked ETH", "cbETH", 18);
        cbethFeed = new MockAggregatorV3(8, "cbETH / USD", CBETH_USD);
        market = new WindDownVenue();

        vm.startPrank(platform);
        factory.setDefaultValuation(address(cbeth), address(cbethFeed));
        factory.setDefaultTarget(address(cbeth), true);
        factory.setDefaultTarget(address(market), true);
        vm.stopPrank();

        // The base fixture's vault froze its valuation set at genesis, so the richer set needs a
        // fresh vault. Every helper inherited from VaultTestBase follows `vault`.
        vault = CuratedVault(factory.createVault(_createParams()));

        // The venue holds no inventory of its own; stock it so it can be on either side of a trade.
        usdc.mint(address(market), 1_000_000e6);
        weth.mint(address(market), 1_000e18);
        cbeth.mint(address(market), 1_000e18);
    }

    // ─────────────────────────────────────────────────────────────────────
    // The boundary — what a pause may never touch
    // ─────────────────────────────────────────────────────────────────────

    /// @dev The single most important assertion in this file. A pause that blocks depositor exits
    ///      is a rug vector, not a safety feature.
    function test_withdrawalSucceedsWhilePaused() public {
        _deposit(alice, 10_000e6);
        _pause();

        vm.prank(alice);
        vault.withdraw(4_000e6, alice, alice);

        assertEq(usdc.balanceOf(alice), 4_000e6, "a paused vault still pays a withdrawal");
        assertTrue(vault.paused(), "and is still paused afterwards");
    }

    function test_redeemSucceedsWhilePaused() public {
        uint256 shares = _deposit(alice, 10_000e6);
        _pause();

        vm.prank(alice);
        uint256 out = vault.redeem(shares, alice, alice);

        assertApproxEqAbs(out, 10_000e6, 1, "a paused vault still honours a full redemption");
        assertEq(vault.balanceOf(alice), 0, "all shares burned");
    }

    /// @dev Allowing deposits is a choice, not an oversight: blocking them would be a liveness power
    ///      the guardian does not need. Pinned so that changing it has to be deliberate.
    function test_depositSucceedsWhilePaused() public {
        _pause();
        uint256 shares = _deposit(alice, 1_000e6);
        assertGt(shares, 0, "deposits are not gated on the pause");
    }

    function test_pausedVaultPricesExactlyAsBefore() public {
        _deposit(alice, 10_000e6);
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});

        uint256 totalBefore = vault.totalAssets();
        uint256 perShareBefore = vault.convertToAssets(1e18);
        uint256 claimBefore = vault.previewRedeem(vault.balanceOf(alice));

        _pause();

        assertEq(vault.totalAssets(), totalBefore, "pausing values nothing differently");
        assertEq(vault.convertToAssets(1e18), perShareBefore, "share price is untouched");
        assertEq(vault.previewRedeem(vault.balanceOf(alice)), claimBefore, "so is the quoted claim");
    }

    // ─────────────────────────────────────────────────────────────────────
    // Who may flip the switch
    // ─────────────────────────────────────────────────────────────────────

    function test_onlyGuardianMayPause() public {
        bytes32 role = vault.GUARDIAN_ROLE();
        address[3] memory outsiders = [agent, alice, platform];

        for (uint256 i; i < outsiders.length; ++i) {
            address caller = outsiders[i];
            vm.expectRevert(
                abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, caller, role)
            );
            vm.prank(caller);
            vault.pause();
        }

        assertFalse(vault.paused(), "still unpaused after three refused attempts");
    }

    function test_onlyGuardianMayUnpause() public {
        _pause();
        bytes32 role = vault.GUARDIAN_ROLE();

        vm.expectRevert(abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, agent, role));
        vm.prank(agent);
        vault.unpause();

        assertTrue(vault.paused(), "the agent cannot lift its own leash");
    }

    /// @dev An emergency control that silently no-ops tells its operator nothing.
    function test_redundantTransitionsRevert() public {
        vm.prank(guardian);
        vm.expectRevert(ICuratedVault.NotPaused.selector);
        vault.unpause();

        _pause();

        vm.prank(guardian);
        vm.expectRevert(ICuratedVault.AlreadyPaused.selector);
        vault.pause();
    }

    function test_bothTransitionsEmitAndAreReadableOnChain() public {
        assertFalse(vault.paused(), "vaults are born trading");

        vm.expectEmit(true, false, false, false, address(vault));
        emit ICuratedVault.TradingPaused(guardian);
        vm.prank(guardian);
        vault.pause();
        assertTrue(vault.paused(), "paused() backs VaultState.paused");

        vm.expectEmit(true, false, false, false, address(vault));
        emit ICuratedVault.TradingUnpaused(guardian);
        vm.prank(guardian);
        vault.unpause();
        assertFalse(vault.paused(), "and comes back");
    }

    // ─────────────────────────────────────────────────────────────────────
    // The wind-down rule — direction, not price
    // ─────────────────────────────────────────────────────────────────────

    /// @dev The property in one test: while paused, the agent cannot acquire anything. No cash is
    ///      spent here — the venue makes a gift — so the *only* thing failing it is the direction.
    function test_windDownRefusesToIncreaseAHolding() public {
        _deposit(alice, 10_000e6);
        _pause();

        vm.expectRevert(
            abi.encodeWithSelector(ICuratedVault.WindDownWouldIncreaseHolding.selector, address(weth), 0, 1e18)
        );
        vm.prank(agent);
        vault.execute(address(market), 0, _swap(address(weth), 0, address(weth), 1e18));
    }

    function test_windDownRefusesToSpendTheBaseAsset() public {
        _deposit(alice, 10_000e6);
        _pause();

        vm.prank(agent);
        vault.approveVenue(address(usdc), address(market), type(uint256).max);

        vm.expectRevert(
            abi.encodeWithSelector(
                ICuratedVault.WindDownWouldSpendBaseAsset.selector, uint256(10_000e6), uint256(7_000e6)
            )
        );
        vm.prank(agent);
        vault.execute(address(market), 0, _swap(address(usdc), 3_000e6, address(weth), 1e18));
    }

    function test_windDownPermitsASale() public {
        _deposit(alice, 10_000e6);
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});
        _pause();

        vm.startPrank(agent);
        vault.approveVenue(address(weth), address(market), type(uint256).max);
        vault.execute(address(market), 0, _swap(address(weth), 2e18, address(usdc), 6_000e6));
        vm.stopPrank();

        assertEq(weth.balanceOf(address(vault)), 0, "the position is gone");
        assertEq(usdc.balanceOf(address(vault)), 10_000e6, "and it came back as cash");
    }

    /// @dev The rule reads balances, never prices. A sale at a catastrophic price satisfies it, and
    ///      pretending otherwise would be the overclaim: what bounds execution quality is `minOut`
    ///      in the calldata and the harness's slippage gate, exactly as when unpaused.
    function test_windDownConstrainsDirectionNotPrice() public {
        _deposit(alice, 10_000e6);
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});
        _pause();

        vm.startPrank(agent);
        vault.approveVenue(address(weth), address(market), type(uint256).max);
        vault.execute(address(market), 0, _swap(address(weth), 2e18, address(usdc), 1));
        vm.stopPrank();

        assertEq(usdc.balanceOf(address(vault)), 4_000e6 + 1, "6,000 USDC of WETH sold for one wei");
        assertLt(vault.totalAssets(), 4_001e6, "the vault is poorer, and the contract permitted it");
    }

    /// @dev Aqua's `dock()` moves no tokens at all under Pattern 1 — it releases an encumbrance
    ///      against balances that never left the vault — and it is the *first* step of every Aqua
    ///      unwind. A rule demanding that cash strictly increase would reject it, which is why the
    ///      rule is "cash must not fall" instead.
    function test_windDownPermitsAValueNeutralCall() public {
        _deposit(alice, 10_000e6);
        _pause();

        vm.prank(agent);
        vault.execute(address(venue), 0, abi.encodeCall(CallTarget.ping, (21)));

        assertEq(venue.callCount(), 1, "a call that moves nothing is not a breach of direction");
    }

    /// @dev Selling a position through a router means approving the router first. A wind-down that
    ///      could not approve could not unwind.
    function test_approvalsStillWorkWhilePaused() public {
        _pause();

        vm.prank(agent);
        vault.approveVenue(address(weth), address(market), 5e18);

        assertEq(weth.allowance(address(vault), address(market)), 5e18, "approvals are not gated");
    }

    /// @dev The whole point of measuring at the end of the batch rather than per step. The same two
    ///      calls are rejected individually and accepted together, which is the difference between
    ///      "you may not hold this token" and "you may not end up holding it".
    function test_windDownMeasuresTheBatchNotEachStep() public {
        _deposit(alice, 10_000e6);
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});
        _pause();

        vm.startPrank(agent);
        vault.approveVenue(address(weth), address(market), type(uint256).max);
        vault.approveVenue(address(cbeth), address(market), type(uint256).max);

        // Leg one alone acquires cbETH, and the rule says no.
        vm.expectRevert(
            abi.encodeWithSelector(ICuratedVault.WindDownWouldIncreaseHolding.selector, address(cbeth), 0, 1.8e18)
        );
        vault.execute(address(market), 0, _swap(address(weth), 2e18, address(cbeth), 1.8e18));

        // The same leg, followed by the one that spends what it bought, is a route to cash.
        ICuratedVault.Call[] memory route = new ICuratedVault.Call[](2);
        route[0] = ICuratedVault.Call({
            target: address(market),
            value: 0,
            data: _swap(address(weth), 2e18, address(cbeth), 1.8e18)
        });
        route[1] = ICuratedVault.Call({
            target: address(market),
            value: 0,
            data: _swap(address(cbeth), 1.8e18, address(usdc), 6_000e6)
        });
        vault.executeBatch(route);
        vm.stopPrank();

        assertEq(weth.balanceOf(address(vault)), 0, "sold");
        assertEq(cbeth.balanceOf(address(vault)), 0, "held only between two calls of one transaction");
        assertEq(usdc.balanceOf(address(vault)), 10_000e6, "and the whole book is cash");
    }

    function test_windDownRuleLiftsWhenUnpaused() public {
        _deposit(alice, 10_000e6);
        _pause();

        vm.prank(guardian);
        vault.unpause();

        vm.prank(agent);
        vault.execute(address(market), 0, _swap(address(weth), 0, address(weth), 1e18));

        assertEq(weth.balanceOf(address(vault)), 1e18, "an unpaused vault may still buy");
    }

    /// @dev The guardian pauses; the *agent* still chooses route and size. A guardian able to name
    ///      the trade would pick the moment and could trade ahead of it — a worse power than the one
    ///      the pause exists to contain.
    function test_guardianStillCannotNameATrade() public {
        _deposit(alice, 10_000e6);
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});
        _pause();

        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, guardian, vault.AGENT_ROLE()
            )
        );
        vm.prank(guardian);
        vault.execute(address(market), 0, _swap(address(weth), 2e18, address(usdc), 6_000e6));
    }

    // ─────────────────────────────────────────────────────────────────────
    // redeemInKind — the exit that cannot fail for want of liquidity
    // ─────────────────────────────────────────────────────────────────────

    /// @dev `SECURITY.md` §10, exactly as measured: 15,000 in `totalAssets()`, 9,000 liquid, and a
    ///      10,000 claim that `redeem` cannot pay. Both halves are asserted in one test so the fix
    ///      and the hole it closes cannot drift apart.
    function test_redeemInKindClosesTheBookSection10CouldNotPay() public {
        uint256 aliceShares = _deposit(alice, 10_000e6);
        _deposit(bob, 5_000e6);
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});

        assertEq(vault.totalAssets(), 15_000e6, "solvent");
        assertEq(usdc.balanceOf(address(vault)), 9_000e6, "but only 9,000 of it is liquid");

        // The hole, still real.
        vm.expectRevert();
        vm.prank(alice);
        vault.redeem(aliceShares, alice, alice);

        // The exit that does not need a market.
        uint256 claim = vault.previewRedeem(aliceShares);
        uint256 totalBefore = vault.totalAssets();

        vm.prank(alice);
        ICuratedVault.InKindPayout[] memory payouts = vault.redeemInKind(aliceShares, alice, alice);

        assertEq(vault.balanceOf(alice), 0, "she is out in full");
        assertApproxEqRel(totalBefore - vault.totalAssets(), claim, 1e12, "and took her whole claim with her");

        assertEq(payouts.length, 3, "base asset plus both registered holdings");
        assertEq(payouts[0].token, address(usdc), "index 0 is always the base asset");
        assertEq(usdc.balanceOf(alice), payouts[0].amount, "paid in cash");
        assertEq(weth.balanceOf(alice), payouts[1].amount, "and in the position she owns a slice of");
        assertGt(payouts[1].amount, 0, "the WETH leg is the part redeem could not reach");
    }

    function test_redeemInKindPaysProRataOfEveryHolding() public {
        uint256 aliceShares = _deposit(alice, 10_000e6);
        _deposit(bob, 5_000e6);
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});

        vm.prank(alice);
        ICuratedVault.InKindPayout[] memory payouts = vault.redeemInKind(aliceShares, alice, alice);

        // Alice owns two thirds of a book of 9,000 USDC and 2 WETH. Asserted against the economics
        // rather than against a re-derivation of the contract's own arithmetic.
        assertApproxEqRel(payouts[0].amount, 6_000e6, 1e12, "two thirds of the cash");
        assertApproxEqRel(payouts[1].amount, 1.333333e18, 1e12, "two thirds of the WETH");
        assertEq(payouts[2].amount, 0, "and two thirds of nothing is nothing");
        assertEq(payouts[2].token, address(cbeth), "an empty holding is still reported");
    }

    /// @dev Nobody is trapped: every holder can leave through this door, and the vault ends empty.
    ///
    ///      The residue is the virtual-share offset rounding down in the vault's favour, not a leak.
    ///      It is a fixed *fraction* of the book (~10⁻¹⁰), which is why the bound below is
    ///      denominated in value rather than in token units: the same negligible fraction is ~1e8
    ///      wei of an 18-decimal token and rounds to nothing at all on a 6-decimal one. A wei-
    ///      denominated bound would have been an assertion about WETH's decimals wearing a
    ///      solvency claim's clothes.
    function test_everyHolderCanLeaveAndTheVaultEmpties() public {
        uint256 aliceShares = _deposit(alice, 10_000e6);
        uint256 bobShares = _deposit(bob, 5_000e6);
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});

        vm.prank(alice);
        vault.redeemInKind(aliceShares, alice, alice);
        vm.prank(bob);
        vault.redeemInKind(bobShares, bob, bob);

        assertEq(vault.totalSupply(), 0, "no shares left");
        assertLe(vault.totalAssets(), 5, "and what remains is worth under a thousandth of a cent");
        assertEq(usdc.balanceOf(alice) + usdc.balanceOf(bob), 9_000e6 - usdc.balanceOf(address(vault)), "all of it out");
        assertGt(weth.balanceOf(alice) + weth.balanceOf(bob), 1.99e18, "and the WETH leg left with them");
    }

    /// @dev The emergency door must not be the more generous one, or it stops being an emergency
    ///      door and becomes an arbitrage. Same virtual denominator as `previewRedeem`, so the
    ///      in-kind basket is worth at most what the front door quoted.
    function test_redeemInKindIsNeverMoreGenerousThanRedeem() public {
        uint256 aliceShares = _deposit(alice, 10_000e6);
        _deposit(bob, 5_000e6);
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});

        uint256 quoted = vault.previewRedeem(aliceShares);
        uint256 totalBefore = vault.totalAssets();

        vm.prank(alice);
        vault.redeemInKind(aliceShares, alice, alice);

        assertLe(totalBefore - vault.totalAssets(), quoted, "the basket is worth no more than the quote");
    }

    function test_redeemInKindWorksWhilePaused() public {
        uint256 aliceShares = _deposit(alice, 10_000e6);
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});
        _pause();

        vm.prank(alice);
        vault.redeemInKind(aliceShares, alice, alice);

        assertEq(vault.balanceOf(alice), 0, "the unconditional exit is unconditional");
    }

    function test_redeemInKindNeedsAnAllowanceForSomeoneElsesShares() public {
        uint256 aliceShares = _deposit(alice, 10_000e6);

        vm.expectRevert();
        vm.prank(bob);
        vault.redeemInKind(aliceShares, bob, alice);

        vm.prank(alice);
        vault.approve(bob, aliceShares);

        vm.prank(bob);
        vault.redeemInKind(aliceShares, bob, alice);

        assertEq(vault.balanceOf(alice), 0, "alice's shares burned");
        assertGt(usdc.balanceOf(bob), 0, "paid to the receiver bob named");
        assertEq(vault.allowance(alice, bob), 0, "and the allowance was spent");
    }

    /// @dev Topics only — the payout *amounts* are asserted above. What this pins is that an in-kind
    ///      exit is legible in the logs at all, so a dashboard can explain one.
    function test_redeemInKindEmitsTheExit() public {
        uint256 aliceShares = _deposit(alice, 1_000e6);

        vm.expectEmit(true, true, true, false, address(vault));
        emit ICuratedVault.RedeemedInKind(alice, alice, alice, 0, new ICuratedVault.InKindPayout[](0));

        vm.prank(alice);
        vault.redeemInKind(aliceShares, alice, alice);
    }

    function test_redeemInKindRejectsAZeroReceiver() public {
        uint256 aliceShares = _deposit(alice, 1_000e6);

        vm.expectRevert(ICuratedVault.ZeroAddress.selector);
        vm.prank(alice);
        vault.redeemInKind(aliceShares, address(0), alice);
    }

    // ─────────────────────────────────────────────────────────────────────
    // Helpers
    // ─────────────────────────────────────────────────────────────────────

    function _pause() private {
        vm.prank(guardian);
        vault.pause();
    }

    function _swap(address tokenIn, uint256 amountIn, address tokenOut, uint256 amountOut)
        private
        pure
        returns (bytes memory)
    {
        return abi.encodeCall(WindDownVenue.swap, (tokenIn, amountIn, tokenOut, amountOut));
    }
}
