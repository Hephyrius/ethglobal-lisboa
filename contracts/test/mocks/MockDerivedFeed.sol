// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAggregatorV3} from "../../src/interfaces/IAggregatorV3.sol";

/// @notice A price feed *derived* from another one — the shape of any wrapper that composes an
///         upstream Chainlink answer with some on-chain quantity.
///
/// @dev Models the real thing Lane D registers for MetaMorpho shares: `convertToAssets(1 share)`
///      multiplied by the underlying's USD price. The vault's valuation set accepts **any** contract
///      answering `IAggregatorV3`, not only a Chainlink-operated aggregator, which is what makes such
///      a wrapper possible at all.
///
///      It also makes a new mistake possible, which is why this mock is switchable rather than
///      fixed. A derived feed has two candidate answers for `updatedAt`:
///
///      - **the upstream's timestamp** — correct. The derived price is exactly as old as the oldest
///        input it was computed from.
///      - **`block.timestamp`** — wrong, and wrong *silently*. The wrapper is computed fresh on every
///        call, so stamping "now" feels right and is trivially defensible in review. It makes the
///        feed permanently self-certify as fresh, which turns `priceMaxAge` into a no-op for that
///        token while every other feed keeps its protection.
///
///      `test/unit/Valuation.t.sol` runs both settings against the vault.
contract MockDerivedFeed is IAggregatorV3 {
    IAggregatorV3 public immutable upstream;
    string private _description;

    /// @notice Multiplier applied to the upstream price, in 1e18 fixed point — stands in for
    ///         `convertToAssets(1 share)`. 1.1e18 means one share is worth 1.1 of the underlying.
    uint256 public exchangeRate = 1e18;

    /// @notice When true, reports `block.timestamp` instead of the upstream's `updatedAt`.
    ///         This is the bug, exposed as a switch so a test can prove it is one.
    bool public stampNowInsteadOfPropagating;

    constructor(IAggregatorV3 upstream_, string memory description_) {
        upstream = upstream_;
        _description = description_;
    }

    function setExchangeRate(uint256 rate) external {
        require(rate <= uint256(type(int256).max), "MockDerivedFeed: rate out of range");
        exchangeRate = rate;
    }

    function setStampNowInsteadOfPropagating(bool on) external {
        stampNowInsteadOfPropagating = on;
    }

    function decimals() external view returns (uint8) {
        return upstream.decimals();
    }

    function description() external view returns (string memory) {
        return _description;
    }

    function latestRoundData() external view returns (uint80, int256, uint256, uint256, uint80) {
        (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredIn) =
            upstream.latestRoundData();

        // Safe: `setExchangeRate` bounds the value to int256's positive range.
        // forge-lint: disable-next-line(unsafe-typecast)
        int256 derived = (answer * int256(exchangeRate)) / 1e18;
        uint256 stamp = stampNowInsteadOfPropagating ? block.timestamp : updatedAt;

        return (roundId, derived, startedAt, stamp, answeredIn);
    }
}
