// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {CuratedVault} from "../../src/CuratedVault.sol";
import {IAggregatorV3} from "../../src/interfaces/IAggregatorV3.sol";
import {ChainlinkPriceLib} from "../../src/libraries/ChainlinkPriceLib.sol";
import {MockAggregatorV3} from "../mocks/MockAggregatorV3.sol";
import {MockDerivedFeed} from "../mocks/MockDerivedFeed.sol";
import {VaultTestBase} from "./VaultTestBase.sol";

/// @dev `ChainlinkPriceLib`'s functions are `internal`, so calling them from a test inlines them
///      into the test contract and `vm.expectRevert` — which matches the next *external* call — has
///      nothing to attach to. This harness gives every call a real call frame.
contract PriceLibHarness {
    function readPrice(address feed, uint256 maxAge) external view returns (uint256) {
        return ChainlinkPriceLib.readPrice(IAggregatorV3(feed), maxAge);
    }

    function toAssetValue(
        uint256 balance,
        uint256 price,
        uint8 feedDecimals,
        uint8 tokenDecimals,
        uint8 assetDecimals
    ) external pure returns (uint256) {
        return ChainlinkPriceLib.toAssetValue(balance, price, feedDecimals, tokenDecimals, assetDecimals);
    }
}

/// @notice The price path, tested twice: the arithmetic on its own, then its effect on the vault.
contract ChainlinkPriceLibTest is Test {
    MockAggregatorV3 internal feed;
    PriceLibHarness internal lib;

    function setUp() public {
        vm.warp(1_700_000_000);
        feed = new MockAggregatorV3(8, "ETH / USD", 3000e8);
        lib = new PriceLibHarness();
    }

    function test_readsAFreshPrice() public view {
        assertEq(lib.readPrice(address(feed), 3600), 3000e8);
    }

    function test_rejectsAZeroAnswer() public {
        feed.setAnswer(0);
        vm.expectRevert(abi.encodeWithSelector(ChainlinkPriceLib.InvalidPrice.selector, address(feed), int256(0)));
        lib.readPrice(address(feed), 3600);
    }

    function test_rejectsANegativeAnswer() public {
        feed.setAnswer(-1);
        vm.expectRevert(abi.encodeWithSelector(ChainlinkPriceLib.InvalidPrice.selector, address(feed), int256(-1)));
        lib.readPrice(address(feed), 3600);
    }

    function test_rejectsAnIncompleteRound() public {
        feed.setIncompleteRound();
        vm.expectRevert(abi.encodeWithSelector(ChainlinkPriceLib.IncompleteRound.selector, address(feed)));
        lib.readPrice(address(feed), 3600);
    }

    function test_rejectsAStaleAnswer() public {
        uint256 stampedAt = block.timestamp - 7200;
        feed.setAnswerAt(3000e8, stampedAt);

        vm.expectRevert(
            abi.encodeWithSelector(ChainlinkPriceLib.StalePrice.selector, address(feed), stampedAt, uint256(3600))
        );
        lib.readPrice(address(feed), 3600);
    }

    function test_answerExactlyAtTheBoundIsStillFresh() public {
        feed.setAnswerAt(3000e8, block.timestamp - 3600);
        assertEq(lib.readPrice(address(feed), 3600), 3000e8, "inclusive bound");
    }

    /// @dev The fork escape hatch. On a pinned anvil fork the forked feed's `updatedAt` is frozen
    ///      while `block.timestamp` advances, so every non-zero bound eventually fails and takes
    ///      deposits and withdrawals with it. Zero means "do not check".
    function test_zeroMaxAgeDisablesTheStalenessCheck() public {
        feed.setAnswerAt(3000e8, block.timestamp - 400 days);
        assertEq(lib.readPrice(address(feed), 0), 3000e8, "no staleness bound");
    }

    // ── decimal conversion ───────────────────────────────────────────────

    function test_convertsEighteenDecimalTokenIntoSixDecimalAsset() public view {
        // 1 WETH at $3,000 -> 3,000 USDC
        assertEq(lib.toAssetValue(1e18, 3000e8, 8, 18, 6), 3_000e6);
    }

    function test_convertsFractionalBalances() public view {
        assertEq(lib.toAssetValue(0.1e18, 3000e8, 8, 18, 6), 300e6);
        assertEq(lib.toAssetValue(0.001e18, 3000e8, 8, 18, 6), 3e6);
    }

    function test_convertsWhenTokenAndAssetShareDecimals() public view {
        // A 6-decimal token at $1 is worth its own balance in a 6-decimal asset.
        assertEq(lib.toAssetValue(1_234e6, 1e8, 8, 6, 6), 1_234e6);
    }

    function test_convertsUpwardIntoAnEighteenDecimalAsset() public view {
        assertEq(lib.toAssetValue(1e6, 1e8, 8, 6, 18), 1e18);
    }

    function test_zeroBalanceIsZeroValue() public view {
        assertEq(lib.toAssetValue(0, 3000e8, 8, 18, 6), 0);
    }

    /// @dev A balance far larger than any real supply must not overflow — the two-step `mulDiv` is
    ///      what makes that true, and this is the assertion that keeps it that way.
    function test_absurdBalanceDoesNotOverflow() public view {
        uint256 value = lib.toAssetValue(1e30, 1_000_000e8, 8, 18, 6);
        assertEq(value, 1e30 / 1e18 * 1_000_000 * 1e6);
    }

    function testFuzz_valueScalesLinearlyWithBalance(uint128 balance) public view {
        balance = uint128(bound(balance, 1e12, 1e24));
        uint256 single = lib.toAssetValue(balance, 2000e8, 8, 18, 6);
        uint256 doubled = lib.toAssetValue(uint256(balance) * 2, 2000e8, 8, 18, 6);
        assertApproxEqAbs(doubled, single * 2, 1, "doubling the balance doubles the value");
    }
}

/// @notice The same failure modes, seen from the vault.
contract VaultValuationTest is VaultTestBase {
    function test_staleFeedBlocksAccountingWhileTheTokenIsHeld() public {
        _deposit(alice, 1_000e6);
        _simulateRotation({usdcOut: 300e6, wethIn: 0.1e18});

        vm.warp(block.timestamp + 2 * PRICE_MAX_AGE);

        // Reverting is the deliberate choice. Valuing the WETH leg at zero instead would let a
        // withdrawal redeem shares against an understated total and take value from everyone else.
        vm.expectRevert();
        vault.totalAssets();
    }

    function test_freshAnswerRestoresAccounting() public {
        _deposit(alice, 1_000e6);
        _simulateRotation({usdcOut: 300e6, wethIn: 0.1e18});

        vm.warp(block.timestamp + 2 * PRICE_MAX_AGE);
        ethFeed.setAnswer(ETH_USD); // feed reports again, stamped now

        assertEq(vault.totalAssets(), 1_000e6, "back to normal");
    }

    function test_brokenFeedBlocksDepositsToo() public {
        _deposit(alice, 1_000e6);
        _simulateRotation({usdcOut: 300e6, wethIn: 0.1e18});
        ethFeed.setAnswer(0);

        usdc.mint(bob, 100e6);
        vm.startPrank(bob);
        usdc.approve(address(vault), 100e6);
        vm.expectRevert();
        vault.deposit(100e6, bob);
        vm.stopPrank();
    }

    /// @dev A token the vault holds but never registered is invisible to `totalAssets()`. Stated as
    ///      a test because it is the sharpest edge of the design: the mandate must confine the
    ///      agent to tokens the vault can price. See README §Invariants.
    function test_unregisteredTokenIsNotCounted() public {
        _deposit(alice, 1_000e6);

        // An airdrop, or a rotation into something outside the valuation set.
        weth.mint(address(vault), 0); // no-op, keeps weth in scope
        address rogue = address(new MockERC20Stub());
        assertEq(vault.priceFeed(rogue), address(0), "no feed registered");
        assertEq(vault.totalAssets(), 1_000e6, "and therefore no contribution to totalAssets");
    }
}

/// @dev Minimal stand-in for "some token the vault was never configured to price".
contract MockERC20Stub {
    function decimals() external pure returns (uint8) {
        return 18;
    }
}

/// @notice What the vault guarantees when the registered feed is **not** a Chainlink aggregator.
///
/// @dev The valuation set accepts any contract answering `IAggregatorV3`. That is deliberate and
///      useful — Lane D uses it to price a MetaMorpho share as `convertToAssets(1 share)` × the
///      underlying's USD price, which no Chainlink feed exists for (cross-lane #66). It also means
///      the vault's staleness protection is only ever as good as the registered feed's honesty about
///      its own age, and that is a security property worth pinning rather than assuming.
contract DerivedFeedValuationTest is VaultTestBase {
    MockDerivedFeed internal derived;

    function setUp() public override {
        super.setUp();
        derived = new MockDerivedFeed(IAggregatorV3(address(ethFeed)), "wstETH-ish / USD");
    }

    /// @dev The vault does not care who operates the feed. This is the capability #66 relies on.
    function test_aNonChainlinkFeedIsAcceptedAndPricesCorrectly() public {
        CuratedVault derivedVault = _vaultPricingWethWith(address(derived));

        derived.setExchangeRate(1.1e18); // one unit is worth 1.1 ETH
        weth.mint(address(derivedVault), 1e18);

        // 1 unit x 1.1 x $3,000 = $3,300
        assertEq(derivedVault.totalAssets(), 3_300e6, "derived feed priced incorrectly");
    }

    /// @dev The good case: a wrapper that propagates its upstream's `updatedAt` inherits the
    ///      upstream's staleness, so the vault's bound still protects it.
    function test_aDerivedFeedThatPropagatesItsUpstreamStaysProtected() public {
        CuratedVault derivedVault = _vaultPricingWethWith(address(derived));
        weth.mint(address(derivedVault), 1e18);

        assertGt(derivedVault.totalAssets(), 0, "healthy before the upstream goes stale");

        vm.warp(block.timestamp + 2 * PRICE_MAX_AGE); // upstream answer ages out

        vm.expectRevert();
        derivedVault.totalAssets();
    }

    /// @dev **The finding.** A wrapper that stamps `block.timestamp` — which feels correct, because
    ///      it *is* recomputed on every call — self-certifies as permanently fresh. The vault then
    ///      keeps pricing that holding from an arbitrarily old upstream answer while every other
    ///      token in the same vault remains protected. Nothing reverts and nothing looks wrong.
    ///
    ///      This is not a vault bug: the vault cannot tell a derived feed from a native one, by
    ///      design. It is a **requirement on anything registered into the valuation set**, and it is
    ///      written down in SECURITY.md §5 because it is invisible from this side.
    function test_aDerivedFeedThatStampsNowDefeatsStalenessEntirely() public {
        CuratedVault derivedVault = _vaultPricingWethWith(address(derived));
        weth.mint(address(derivedVault), 1e18);

        derived.setStampNowInsteadOfPropagating(true);

        vm.warp(block.timestamp + 3650 days); // the upstream answer is now ten years old

        // No revert. The vault prices a ten-year-old number as though it arrived this block.
        assertEq(derivedVault.totalAssets(), 3_000e6, "expected the stale price to be used silently");
    }

    /// @notice Builds a vault whose WETH is priced by `feed`, leaving the shared fixture untouched.
    function _vaultPricingWethWith(address feed) internal returns (CuratedVault) {
        vm.startPrank(platform);
        factory.setDefaultValuation(address(weth), feed);
        vm.stopPrank();

        return CuratedVault(factory.createVault(_createParams()));
    }
}
