// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAggregatorV3} from "../../src/interfaces/IAggregatorV3.sol";

/// @notice A Chainlink feed whose answer, timestamp and decimals are all settable.
/// @dev Lets the suite drive the failure modes that matter and that a live feed will not reproduce
///      on demand: a negative answer, a zero answer, a round that never completed, and an answer
///      old enough to trip the staleness bound.
contract MockAggregatorV3 is IAggregatorV3 {
    uint8 private _decimals;
    string private _description;

    int256 private _answer;
    uint256 private _updatedAt;
    uint80 private _roundId;

    constructor(uint8 decimals_, string memory description_, int256 answer_) {
        _decimals = decimals_;
        _description = description_;
        _answer = answer_;
        _updatedAt = block.timestamp;
        _roundId = 1;
    }

    function decimals() external view returns (uint8) {
        return _decimals;
    }

    function description() external view returns (string memory) {
        return _description;
    }

    function latestRoundData() external view returns (uint80, int256, uint256, uint256, uint80) {
        return (_roundId, _answer, _updatedAt, _updatedAt, _roundId);
    }

    // ── controls ─────────────────────────────────────────────────────────

    /// @notice Publish a new answer, stamped now.
    function setAnswer(int256 answer_) external {
        _answer = answer_;
        _updatedAt = block.timestamp;
        _roundId++;
    }

    /// @notice Publish an answer stamped at an arbitrary time, to age a feed on demand.
    function setAnswerAt(int256 answer_, uint256 updatedAt_) external {
        _answer = answer_;
        _updatedAt = updatedAt_;
        _roundId++;
    }

    /// @notice Simulate a round that was started but never answered (`updatedAt == 0`).
    function setIncompleteRound() external {
        _updatedAt = 0;
    }
}
