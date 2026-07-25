// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

interface IERC4626Minimal {
    function convertToAssets(uint256 shares) external view returns (uint256);
    function asset() external view returns (address);
    function decimals() external view returns (uint8);
}

interface IERC20Decimals {
    function decimals() external view returns (uint8);
}

interface IAggregatorV3 {
    function decimals() external view returns (uint8);
    function description() external view returns (string memory);
    function version() external view returns (uint256);
    function getRoundData(uint80 roundId)
        external
        view
        returns (uint80, int256, uint256, uint256, uint80);
    function latestRoundData()
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound);
}

/**
 * @title ERC4626PriceFeed
 * @notice Prices one share of an ERC-4626 vault in USD, behind the Chainlink
 *         `AggregatorV3` interface, so the curated vault can value it with **no
 *         contract change**.
 *
 * @dev Why this exists.
 *
 *      `CuratedVault.totalAssets()` values a held token through
 *      `priceFeed(token)` — one Chainlink aggregator per token — and nothing
 *      else. That is exactly right for an Aave aToken, which is a **1:1
 *      rebasing** claim: the underlying's own feed prices it correctly, which
 *      is why Aave needed no new contract.
 *
 *      A MetaMorpho share is not that. It **appreciates** instead of rebasing —
 *      measured on Base, Moonwell Flagship USDC is 1.082362 USDC per share and
 *      Gauntlet USDC Prime 1.104646 — and no Chainlink feed exists for it. So
 *      registering the underlying's feed would understate the position by 8–10%
 *      today and by more every block.
 *
 *      This adapter closes that gap from **Lane D's side**: it is an ordinary
 *      `AggregatorV3` that any vault can already consume, so lending into
 *      MetaMorpho needs a registration, not a change to `contracts/`.
 *
 * @dev The subtle part: **timestamps are passed through, never invented.**
 *
 *      `convertToAssets` is read live and is therefore always current. If this
 *      contract reported `block.timestamp` as `updatedAt`, the price would
 *      *always look fresh* and the vault's staleness check would be silently
 *      defeated — including on the half of the calculation that can genuinely
 *      go stale, the asset's USD price. So the underlying feed's `roundId`,
 *      `startedAt`, `updatedAt` and `answeredInRound` are returned unmodified.
 *      A stale USDC/USD answer makes this feed stale too, which is correct.
 *
 * @dev Manipulation, stated honestly.
 *
 *      `convertToAssets` is a share price, and share prices can be pushed by
 *      donating to the vault. Two things bound it here: MetaMorpho uses
 *      OpenZeppelin's virtual-shares 4626 (the same defence our own vault uses),
 *      and the target vaults hold $9M–$426M, so moving the ratio meaningfully
 *      costs more than it could extract from a hackathon vault. It is a real
 *      property of the design rather than an oversight, and a
 *      TWAP/bounded-growth wrapper is the production answer.
 */
contract ERC4626PriceFeed is IAggregatorV3 {
    /// @notice The ERC-4626 vault whose share is being priced.
    IERC4626Minimal public immutable shareToken;

    /// @notice Chainlink feed for the vault's underlying asset (e.g. USDC/USD).
    IAggregatorV3 public immutable assetFeed;

    /// @dev 10 ** share decimals — "one whole share", the unit priced.
    uint256 public immutable oneShare;

    /// @dev 10 ** asset decimals — cancels the asset units out of the product.
    uint256 public immutable oneAsset;

    /// @notice Chainlink's USD convention. Kept equal to the asset feed's own
    ///         decimals so the arithmetic below needs no rescaling.
    uint8 public immutable decimals;

    string private _description;

    error AssetFeedDecimalsMismatch(uint8 expected, uint8 actual);
    error InvalidUnderlyingPrice(int256 answer);
    error ZeroSharePrice();

    constructor(address vault_, address assetFeed_, string memory description_) {
        shareToken = IERC4626Minimal(vault_);
        assetFeed = IAggregatorV3(assetFeed_);
        _description = description_;

        oneShare = 10 ** IERC4626Minimal(vault_).decimals();
        oneAsset = 10 ** IERC20Decimals(IERC4626Minimal(vault_).asset()).decimals();
        decimals = IAggregatorV3(assetFeed_).decimals();
    }

    function description() external view returns (string memory) {
        return _description;
    }

    function version() external pure returns (uint256) {
        return 4;
    }

    /**
     * @notice USD value of one whole share, in `decimals` fixed point.
     * @dev `assetsPerShare` is in asset units; multiplying by the asset's USD
     *      price and dividing by one asset unit leaves USD in the feed's own
     *      decimals, with no rescaling and no precision loss beyond the final
     *      integer division.
     */
    function latestRoundData()
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound)
    {
        (roundId, answer, startedAt, updatedAt, answeredInRound) = assetFeed.latestRoundData();
        answer = _sharePrice(answer);
    }

    /// @dev Historical rounds price the *current* share ratio against a past
    ///      asset price. There is no historical `convertToAssets`, and pretending
    ///      otherwise would be worse than saying so here.
    function getRoundData(uint80 roundId_)
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound)
    {
        (roundId, answer, startedAt, updatedAt, answeredInRound) = assetFeed.getRoundData(roundId_);
        answer = _sharePrice(answer);
    }

    function _sharePrice(int256 assetUsd) internal view returns (int256) {
        // Mirror the consuming vault's own policy: revert rather than return a
        // number that is confidently wrong.
        if (assetUsd <= 0) revert InvalidUnderlyingPrice(assetUsd);

        uint256 assetsPerShare = shareToken.convertToAssets(oneShare);
        if (assetsPerShare == 0) revert ZeroSharePrice();

        return int256(assetsPerShare * uint256(assetUsd) / oneAsset);
    }
}
