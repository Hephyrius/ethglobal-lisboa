// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Minimal Chainlink price feed interface.
/// @notice Only the members `ChainlinkPriceLib` actually reads. Declared here rather than vendoring
///         Chainlink's npm package for a single interface — it brings a large tree and its own
///         solc-version constraints for no benefit.
/// @dev Matches Chainlink's `AggregatorV3Interface` exactly, so any live Base feed satisfies it.
interface IAggregatorV3 {
    /// @return The number of decimals in `answer`. USD feeds on Base use 8.
    function decimals() external view returns (uint8);

    /// @return Human-readable feed name, e.g. "ETH / USD".
    function description() external view returns (string memory);

    /// @return roundId          The round the answer came from.
    /// @return answer           The price, scaled by `decimals()`. Signed; a non-positive value
    ///                          means the feed is not reporting and must never be trusted.
    /// @return startedAt        Round start timestamp.
    /// @return updatedAt        When `answer` was last written. This is the staleness clock.
    /// @return answeredInRound  Round in which the answer was computed.
    function latestRoundData()
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound);
}
