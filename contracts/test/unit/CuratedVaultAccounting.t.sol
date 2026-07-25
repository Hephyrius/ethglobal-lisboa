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

    /// @dev The classic ERC-4626 first-depositor attack: seed the vault with 1 wei, donate a large
    ///      balance directly to inflate the share price, and the next depositor rounds to zero
    ///      shares. `_decimalsOffset() = 12` is what stops it — OpenZeppelin's virtual shares make
    ///      the donation 10^12 times less effective.
    function test_inflationAttackIsMitigated() public {
        address attacker = makeAddr("attacker");
        _deposit(attacker, 1);

        usdc.mint(attacker, 10_000e6);
        vm.prank(attacker);
        // The unchecked return is the point: this is a raw donation, deliberately bypassing
        // deposit() so no shares are minted against it.
        // forge-lint: disable-next-line(erc20-unchecked-transfer)
        usdc.transfer(address(vault), 10_000e6);

        uint256 victimShares = _deposit(bob, 1_000e6);

        assertGt(victimShares, 0, "victim must not round to zero shares");
        assertApproxEqRel(
            vault.convertToAssets(victimShares), 1_000e6, 1e16, "victim keeps ~all of the deposit's value"
        );
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
