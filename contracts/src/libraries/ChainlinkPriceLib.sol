// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

import {IAggregatorV3} from "../interfaces/IAggregatorV3.sol";

/// @title ChainlinkPriceLib — read a feed, refuse to trust a bad one, convert decimals.
/// @notice Split out of the vault so the arithmetic that decides share price can be tested on its
///         own, without deploying a vault or a token.
library ChainlinkPriceLib {
    /// @dev The answer is older than the caller is willing to accept. See `readPrice`.
    error StalePrice(address feed, uint256 updatedAt, uint256 maxAge);
    /// @dev A non-positive answer means the feed is not reporting. Never treat it as zero value.
    error InvalidPrice(address feed, int256 answer);
    /// @dev `updatedAt == 0` marks a round that was never completed.
    error IncompleteRound(address feed);

    /// @notice Latest price from `feed`, as an unsigned integer scaled by the feed's own decimals.
    ///
    /// @param maxAge Maximum acceptable age of the answer in seconds. **0 disables the check.**
    ///
    ///        Zero is not a footgun left open by accident — it is required on a pinned anvil fork.
    ///        The forked feed's `updatedAt` is frozen at the fork block while `block.timestamp`
    ///        keeps advancing, so any non-zero bound starts failing minutes into a dev session and
    ///        takes `totalAssets()`, deposits and withdrawals down with it. Fork deployments pass 0;
    ///        mainnet passes the feed's heartbeat (3600s covers Base's 1200s ETH/USD heartbeat with
    ///        margin).
    ///
    /// @dev Reverts rather than returning zero on a bad answer. Valuing a held token at zero would
    ///      silently misprice shares and let a withdrawal drain value from the remaining holders;
    ///      a revert blocks the deposit or withdrawal instead, which is the failure we want.
    function readPrice(IAggregatorV3 feed, uint256 maxAge) internal view returns (uint256 price) {
        (, int256 answer,, uint256 updatedAt,) = feed.latestRoundData();

        if (updatedAt == 0) revert IncompleteRound(address(feed));
        if (answer <= 0) revert InvalidPrice(address(feed), answer);

        // A freshness check has no other clock to read. The bound is measured in hours, so the few
        // seconds a proposer could shift `block.timestamp` cannot turn a stale answer into a fresh
        // one or the reverse.
        // forge-lint: disable-next-line(block-timestamp)
        if (maxAge != 0 && block.timestamp > updatedAt + maxAge) {
            revert StalePrice(address(feed), updatedAt, maxAge);
        }

        // Safe: `answer <= 0` reverted two lines above, so the value is strictly positive and
        // within int256, which is a subset of uint256.
        // forge-lint: disable-next-line(unsafe-typecast)
        return uint256(answer);
    }

    /// @notice Convert a token balance into base-asset units at `price`.
    ///
    /// @dev `value = balance × price ÷ 10^feedDecimals × 10^assetDecimals ÷ 10^tokenDecimals`
    ///
    ///      Done as two `Math.mulDiv` calls so the intermediate product uses the full 512-bit path
    ///      and cannot overflow, even for an implausible balance or a feed reporting a garbage
    ///      price. Truncation is toward zero at each step — at the magnitudes involved
    ///      (WETH priced in USDC) the error is far below one base unit, and rounding *down* is the
    ///      correct direction for a vault: it can only ever understate what is held.
    ///
    ///      **Assumption, stated plainly:** the feed quotes the token in USD and one base-asset
    ///      unit is treated as exactly $1. True enough for USDC; it is the one approximation in the
    ///      share-price path, and pricing the asset leg through its own feed is a stretch item.
    function toAssetValue(
        uint256 balance,
        uint256 price,
        uint8 feedDecimals,
        uint8 tokenDecimals,
        uint8 assetDecimals
    ) internal pure returns (uint256) {
        if (balance == 0) return 0;
        uint256 usdScaled = Math.mulDiv(balance, price, 10 ** feedDecimals);
        return Math.mulDiv(usdScaled, 10 ** assetDecimals, 10 ** tokenDecimals);
    }
}
