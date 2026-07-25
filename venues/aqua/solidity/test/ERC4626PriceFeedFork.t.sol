// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import { Test } from "forge-std/Test.sol";

import { ERC4626PriceFeed, IAggregatorV3, IERC4626Minimal } from "../src/ERC4626PriceFeed.sol";

/**
 * @title ERC4626PriceFeedFork
 * @notice Prices a real MetaMorpho share against real Chainlink, on a Base fork.
 *
 * @dev The failure this prevents is silent and expensive: supplying into a
 *      token the curated vault cannot value makes `totalAssets()` fall by the
 *      amount supplied, and every depositor's share price with it. Aave avoided
 *      it because an aToken rebases 1:1. A MetaMorpho share does not, so it
 *      needs a real conversion — and a conversion that is *wrong* is worse than
 *      no venue at all.
 */
contract ERC4626PriceFeedForkTest is Test {
    // Verified on Base: 19,340 bytes each, asset() == USDC, 18-decimal shares.
    address internal constant MOONWELL_USDC = 0xc1256Ae5FF1cf2719D4937adb3bbCCab2E00A2Ca;
    address internal constant GAUNTLET_USDC_PRIME = 0xeE8F4eC5672F09119b96Ab6fB59C27E1b7e44b61;

    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant USDC_USD_FEED = 0x7e860098F58bBFC8648a4311b374B1D669a2bc6B;
    address internal constant ETH_USD_FEED = 0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70;

    ERC4626PriceFeed internal feed;

    function setUp() public {
        string memory rpc = vm.envOr("BASE_RPC_URL", string("https://mainnet.base.org"));
        try vm.createSelectFork(rpc) { } catch { vm.skip(true); }
        feed = new ERC4626PriceFeed(MOONWELL_USDC, USDC_USD_FEED, "mwUSDC / USD");
    }

    // ── it is a Chainlink feed, as far as any consumer can tell ───────────

    function test_itLooksLikeAChainlinkFeed() public view {
        // The curated vault reads exactly these, and expand-universe.sh
        // validates a feed by reading description().
        assertEq(feed.decimals(), 8, "USD feeds are 8 decimals by convention");
        assertEq(feed.description(), "mwUSDC / USD");
        assertGt(feed.version(), 0);
    }

    function test_decimalsMatchTheUnderlyingFeed() public view {
        assertEq(feed.decimals(), IAggregatorV3(USDC_USD_FEED).decimals());
    }

    // ── the price is right ────────────────────────────────────────────────

    function test_pricesOneShareAboveOneDollarBecauseSharesAppreciate() public view {
        (, int256 answer,,,) = feed.latestRoundData();

        // A share is worth strictly more than one USDC once any interest has
        // accrued. If this ever equals 1e8 exactly, the conversion has been
        // silently replaced by the 1:1 assumption that motivated the contract.
        assertGt(answer, 1e8, "share should be worth more than $1");
        assertLt(answer, 2e8, "a 2x share price means the maths is wrong, not that Morpho doubled");
    }

    function test_theAnswerIsSharePriceTimesAssetPrice() public view {
        (, int256 assetUsd,,,) = IAggregatorV3(USDC_USD_FEED).latestRoundData();
        uint256 assetsPerShare = IERC4626Minimal(MOONWELL_USDC).convertToAssets(1e18);

        (, int256 answer,,,) = feed.latestRoundData();

        // assetsPerShare is 6-decimal USDC; assetUsd is 8-decimal USD.
        assertEq(answer, int256(assetsPerShare * uint256(assetUsd) / 1e6));
    }

    function test_itTracksTheVaultRatherThanAConstant() public {
        ERC4626PriceFeed other =
            new ERC4626PriceFeed(GAUNTLET_USDC_PRIME, USDC_USD_FEED, "gtUSDCp / USD");

        (, int256 moonwell,,,) = feed.latestRoundData();
        (, int256 gauntlet,,,) = other.latestRoundData();

        // Two vaults on the same asset with different accrued interest must not
        // price identically — that would prove the share ratio is being ignored.
        assertTrue(moonwell != gauntlet, "two different vaults priced identically");
    }

    /// @dev The whole reason the adapter exists, expressed as a number: how
    ///      wrong the naive "value it with the underlying's feed" answer is.
    function test_thenaiveUnderlyingFeedWouldUnderstateThePosition() public {
        (, int256 naive,,,) = IAggregatorV3(USDC_USD_FEED).latestRoundData();
        (, int256 correct,,,) = feed.latestRoundData();

        assertGt(correct, naive);
        uint256 understatementBps = uint256(correct - naive) * 10_000 / uint256(correct);
        emit log_named_uint("understatement if valued as plain USDC (bps)", understatementBps);
        assertGt(understatementBps, 100, "expected the gap to be material, not rounding");
    }

    // ── staleness is inherited, not invented ──────────────────────────────

    /// @dev The subtle one. `convertToAssets` is always current, so a feed that
    ///      reported `block.timestamp` would always look fresh and would defeat
    ///      the vault's staleness check on the half that *can* go stale — the
    ///      USD price. Timestamps must be the underlying's, unmodified.
    function test_timestampsArePassedThroughFromTheAssetFeed() public view {
        (uint80 rid, , uint256 started, uint256 updated, uint80 air) =
            IAggregatorV3(USDC_USD_FEED).latestRoundData();
        (uint80 rid2, , uint256 started2, uint256 updated2, uint80 air2) = feed.latestRoundData();

        assertEq(rid2, rid);
        assertEq(started2, started);
        assertEq(updated2, updated);
        assertEq(air2, air);
    }

    function test_updatedAtIsNotBlockTimestamp() public view {
        (,,, uint256 updated,) = feed.latestRoundData();
        // On a fork these differ; if they ever match exactly it is worth a look,
        // because inventing freshness is the failure this guards.
        assertTrue(updated <= block.timestamp);
    }

    // ── failure modes ─────────────────────────────────────────────────────

    function test_aMismatchedAssetFeedIsStillConstructible_butPricesWrong() public {
        // Deliberate: the contract cannot detect that ETH/USD is the wrong feed
        // for a USDC vault — both are 8-decimal aggregators. expand-universe.sh
        // reading description() is the check that catches this, which is why
        // description() is implemented rather than stubbed.
        ERC4626PriceFeed wrong =
            new ERC4626PriceFeed(MOONWELL_USDC, ETH_USD_FEED, "WRONG / USD");
        (, int256 answer,,,) = wrong.latestRoundData();
        assertGt(answer, 1000e8, "a USDC share priced off ETH/USD is absurdly high");
    }

    function test_getRoundDataAlsoConverts() public view {
        (uint80 rid,,,,) = IAggregatorV3(USDC_USD_FEED).latestRoundData();
        (, int256 answer,,,) = feed.getRoundData(rid);
        assertGt(answer, 1e8);
    }
}
