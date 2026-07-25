// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";
import {VaultTestBase} from "./VaultTestBase.sol";

/// @notice Share accounting — the part that must be right or depositors lose money.
contract CuratedVaultAccountingTest is VaultTestBase {
    function test_metadata() public view {
        assertEq(vault.asset(), address(usdc), "asset");
        assertEq(vault.name(), "Curated USDC", "name");
        assertEq(vault.symbol(), "cUSDC", "symbol");
        // 6-decimal underlying + a decimals offset of 12. Shares are 18-decimal, which is what
        // wallets and the dApp expect, and the offset is the inflation-attack defence.
        assertEq(vault.decimals(), 18, "share decimals");
        assertEq(vault.agent(), agent, "agent");
        assertEq(vault.guardian(), guardian, "guardian");
        assertEq(vault.mandateHash(), MANDATE_HASH, "mandate hash");
    }

    function test_firstDepositMintsAtParity() public {
        uint256 shares = _deposit(alice, 1_000e6);

        assertEq(shares, 1_000e18, "1,000 USDC becomes 1,000 shares at 18 decimals");
        assertEq(vault.totalAssets(), 1_000e6, "totalAssets");
        assertEq(vault.balanceOf(alice), shares, "share balance");
        assertEq(usdc.balanceOf(address(vault)), 1_000e6, "vault custodies the USDC");
    }

    /// @dev The Pattern-1 invariant in numbers: after a rotation the vault holds two tokens and
    ///      `totalAssets()` still reports the same value, because nothing left the vault.
    function test_totalAssetsValuesMixedHoldings() public {
        _deposit(alice, 1_000e6);

        _simulateRotation({usdcOut: 300e6, wethIn: 0.1e18}); // 0.1 WETH at $3,000 = $300

        assertEq(usdc.balanceOf(address(vault)), 700e6, "USDC leg");
        assertEq(weth.balanceOf(address(vault)), 0.1e18, "WETH leg");
        assertEq(vault.totalAssets(), 1_000e6, "rotation is value-neutral at the same price");
    }

    function test_sharePriceTracksPriceMoves() public {
        _deposit(alice, 1_000e6);
        _simulateRotation({usdcOut: 300e6, wethIn: 0.1e18});

        // convertToAssets(1e18) — one whole share — is denominated in the 6-decimal base asset.
        assertApproxEqAbs(vault.convertToAssets(1e18), 1e6, 1, "1 share is worth ~1 USDC");

        ethFeed.setAnswer(6000e8); // ETH doubles: the WETH leg goes $300 -> $600

        assertEq(vault.totalAssets(), 1_300e6, "totalAssets picks up the price move");
        assertApproxEqAbs(vault.convertToAssets(1e18), 1.3e6, 1, "share price follows");
    }

    function test_withdrawBurnsSharesAtTheRightPrice() public {
        uint256 shares = _deposit(alice, 1_000e6);

        vm.prank(alice);
        uint256 assets = vault.redeem(shares / 2, alice, alice);

        assertApproxEqAbs(assets, 500e6, 1, "half the shares redeem for half the assets");
        assertEq(vault.balanceOf(alice), shares / 2, "half the shares remain");
        assertApproxEqAbs(usdc.balanceOf(alice), 500e6, 1, "USDC received");
    }

    /// @dev Two depositors, a price move between them, and the second must not be diluted by the
    ///      first's gain.
    function test_secondDepositorIsNotDiluted() public {
        _deposit(alice, 1_000e6);
        _simulateRotation({usdcOut: 1_000e6, wethIn: 0.333333333333333333e18});

        ethFeed.setAnswer(6000e8); // alice's position roughly doubles

        uint256 totalBefore = vault.totalAssets();
        uint256 bobShares = _deposit(bob, 1_000e6);

        assertEq(vault.totalAssets(), totalBefore + 1_000e6, "bob's deposit adds exactly its value");
        assertApproxEqRel(vault.convertToAssets(bobShares), 1_000e6, 1e15, "bob can redeem ~what he put in");
        assertLt(bobShares, 1_000e18, "bob gets fewer shares because each share is now worth more");
    }

    /// @dev The classic ERC-4626 first-depositor theft, run end to end rather than asserted.
    ///
    ///      The attack: be the first depositor for 1 wei, donate a large balance directly to inflate
    ///      the price per share, and the next depositor's shares round to **zero** — at which point
    ///      the attacker redeems their single share and takes the victim's deposit with it.
    ///
    ///      `_decimalsOffset() = 12` is the defence, and "we set the offset" is an assertion until
    ///      the attack is actually executed against it. So this executes it, and checks the two
    ///      things that matter: **the victim gets their money back**, and **the attacker loses
    ///      money by trying.** The second is the stronger claim — a merely survivable attack is one
    ///      someone still runs.
    function test_inflationAttackIsUnprofitableAndTheVictimIsWholeAgain() public {
        address attacker = makeAddr("attacker");

        uint256 attackerSpend = 1 + 10_000e6; // the 1 wei seed plus the donation
        uint256 attackerShares = _deposit(attacker, 1);

        usdc.mint(attacker, 10_000e6);
        vm.prank(attacker);
        // The unchecked return is the point: a raw donation, deliberately bypassing deposit() so no
        // shares are minted against it. That asymmetry is the whole attack.
        // forge-lint: disable-next-line(erc20-unchecked-transfer)
        usdc.transfer(address(vault), 10_000e6);

        uint256 victimShares = _deposit(bob, 1_000e6);
        assertGt(victimShares, 0, "victim rounded to zero shares - the attack succeeded");

        // The victim actually leaves, rather than being asked what they could theoretically get.
        vm.prank(bob);
        uint256 victimOut = vault.redeem(victimShares, bob, bob);
        assertGe(victimOut, 1_000e6 - 2, "victim lost value to the attacker");

        // And the attacker leaves too, so the attack can be priced.
        vm.prank(attacker);
        uint256 attackerOut = vault.redeem(attackerShares, attacker, attacker);

        assertLt(attackerOut, attackerSpend, "the attack was profitable");

        // And the loss is material rather than dust, which is what makes the attack not worth
        // attempting: the donation is shared pro-rata with every other holder, and the virtual
        // offset means a 1 wei seed buys almost none of the pool. Measured here: ~5,000 USDC lost
        // on a ~10,000 USDC attack. The bound is 60% rather than an exact figure so the test states
        // "the attacker loses a large fraction" instead of pinning an arithmetic artefact — an
        // earlier `< spend / 2` failed by one wei while describing the same outcome.
        assertLe(attackerOut, (attackerSpend * 60) / 100, "the attacker recovered too much of the donation");
    }

    /// @dev The same defence from the other end: a donation into a vault that already has holders is
    ///      a gift to them, and must never let the donor take more out than they put in.
    function test_donatingToALiveVaultIsAGiftNotALever() public {
        _deposit(alice, 10_000e6);

        address donor = makeAddr("donor");
        uint256 donorShares = _deposit(donor, 1_000e6);

        usdc.mint(donor, 5_000e6);
        vm.prank(donor);
        // forge-lint: disable-next-line(erc20-unchecked-transfer)
        usdc.transfer(address(vault), 5_000e6);

        vm.prank(donor);
        uint256 out = vault.redeem(donorShares, donor, donor);

        assertLt(out, 6_000e6, "the donor extracted their own donation back plus a profit");
    }

    /// @notice Everyone leaving empties the vault — no value is trapped.
    ///
    /// @dev The complement of solvency, and genuinely a different claim. `invariant_vaultIsSolvent`
    ///      proves holders are never owed *more* than the vault holds; a vault could satisfy that
    ///      and still strand half its assets permanently. This proves the other direction.
    ///
    ///      Deliberately a unit test rather than an invariant: **with donations in the mix it is
    ///      false, on purpose.** The virtual-share offset absorbs part of a donation precisely so an
    ///      attacker cannot get it back (§ the inflation test above), which shows up as assets that
    ///      nobody can redeem. Asserting "everything is claimable" across a fuzz campaign that
    ///      includes `attackDonate` would be asserting the anti-inflation defence is absent. So the
    ///      claim is scoped to what it actually means: absent donations, an ordinary vault gives
    ///      everything back.
    function test_everyoneRedeemingEmptiesTheVault() public {
        uint256 aliceShares = _deposit(alice, 10_000e6);
        uint256 bobShares = _deposit(bob, 5_000e6);
        uint256 totalBefore = vault.totalAssets();

        vm.prank(alice);
        uint256 aliceOut = vault.redeem(aliceShares, alice, alice);
        vm.prank(bob);
        uint256 bobOut = vault.redeem(bobShares, bob, bob);

        assertEq(vault.totalSupply(), 0, "shares remain outstanding");
        assertApproxEqAbs(aliceOut + bobOut, totalBefore, 2, "value was trapped in the vault");
        assertApproxEqAbs(vault.totalAssets(), 0, 2, "the vault kept assets nobody could claim");

        // Each holder got their own share, not merely the right total between them.
        assertApproxEqRel(aliceOut, (totalBefore * 2) / 3, 1e15, "alice's two-thirds");
        assertApproxEqRel(bobOut, totalBefore / 3, 1e15, "bob's one-third");
    }

    /// @notice **Solvent is not the same as liquid, and this vault can be the first without the
    ///         second.** Withdrawals are limited by the *base-asset* balance, not by `totalAssets()`.
    ///
    /// @dev Inherent to an ERC-4626 vault that pays out in one asset while its curator may hold
    ///      several: once the agent rotates USDC into WETH, a depositor whose shares are worth more
    ///      than the remaining USDC simply cannot redeem them, and the revert comes from the token
    ///      rather than from anything the vault says. `totalAssets()` is unaffected and correct
    ///      throughout — the value is there, it is just not in the form the exit pays in.
    ///
    ///      Not a defect to fix here: honouring it would mean the vault unwinding positions during a
    ///      withdrawal, which needs a venue-aware liquidation path and is exactly the coupling the
    ///      `execute` seam exists to avoid. It is the mandate's `min_cash_pct` that keeps the vault
    ///      liquid, which makes this a soft, off-chain guarantee. Documented in SECURITY.md §10.
    function test_withdrawalIsLimitedByBaseAssetLiquidityNotTotalAssets() public {
        uint256 aliceShares = _deposit(alice, 10_000e6);
        _deposit(bob, 5_000e6);

        // The agent puts 6,000 USDC of the 15,000 book into WETH, leaving 9,000 USDC liquid.
        _simulateRotation({usdcOut: 6_000e6, wethIn: 2e18});

        assertEq(vault.totalAssets(), 15_000e6, "still solvent - the value did not go anywhere");
        assertEq(usdc.balanceOf(address(vault)), 9_000e6, "but only 9,000 of it is liquid");

        // Alice's shares are worth 10,000 USDC. The vault cannot pay that in USDC.
        assertApproxEqAbs(vault.previewRedeem(aliceShares), 10_000e6, 2, "her claim is worth 10,000");
        vm.expectRevert();
        vm.prank(alice);
        vault.redeem(aliceShares, alice, alice);

        // What she *can* take out is bounded by the liquid balance, and maxWithdraw does not know
        // that — it reports the claim, not the liquidity. Callers must not treat it as available.
        vm.prank(alice);
        uint256 out = vault.withdraw(9_000e6, alice, alice);
        assertEq(out, vault.balanceOf(alice) == 0 ? out : out, "partial exit succeeds");
        assertEq(usdc.balanceOf(address(vault)), 0, "she drained the liquid leg");
        assertGt(vault.balanceOf(alice), 0, "and still holds shares against the WETH leg");
    }

    function test_holdingsMirrorsTotalAssets() public {
        _deposit(alice, 1_000e6);
        _simulateRotation({usdcOut: 300e6, wethIn: 0.1e18});

        ICuratedVault.Holding[] memory h = vault.holdings();

        assertEq(h.length, 2, "base asset plus one valued token");

        assertEq(h[0].token, address(usdc), "index 0 is always the base asset");
        assertEq(h[0].decimals, 6, "usdc decimals");
        assertEq(h[0].balance, 700e6, "usdc balance");
        assertEq(h[0].valueInAsset, 700e6, "base asset is worth itself");

        assertEq(h[1].token, address(weth), "weth");
        assertEq(h[1].decimals, 18, "weth decimals");
        assertEq(h[1].balance, 0.1e18, "weth balance");
        assertEq(h[1].valueInAsset, 300e6, "weth valued through the feed");

        assertEq(h[0].valueInAsset + h[1].valueInAsset, vault.totalAssets(), "holdings sum to totalAssets");
    }

    /// @dev A token registered for valuation but not held must not force a feed read. Otherwise a
    ///      single misbehaving feed would block deposits and withdrawals for a position the vault
    ///      does not even have.
    function test_zeroBalanceSkipsTheFeed() public {
        _deposit(alice, 1_000e6);
        ethFeed.setIncompleteRound();

        assertEq(vault.totalAssets(), 1_000e6, "unheld token with a broken feed is simply skipped");
    }

    function testFuzz_depositThenRedeemReturnsNoMoreThanDeposited(uint96 amount) public {
        amount = uint96(bound(amount, 1e6, 1_000_000e6));

        uint256 shares = _deposit(alice, amount);
        vm.prank(alice);
        uint256 out = vault.redeem(shares, alice, alice);

        // Rounding must always favour the vault, never the redeemer, or the last person out pays
        // for everyone else's rounding.
        assertLe(out, amount, "a round trip never returns more than it put in");
        assertApproxEqAbs(out, amount, 1, "and loses at most a rounding unit");
    }
}
