// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {CuratedVault} from "../../src/CuratedVault.sol";
import {VaultFactory} from "../../src/VaultFactory.sol";
import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";
import {IVaultFactory} from "../../src/interfaces/IVaultFactory.sol";

import {CallTarget} from "../mocks/CallTarget.sol";
import {MockAggregatorV3} from "../mocks/MockAggregatorV3.sol";
import {MockERC20} from "../mocks/MockERC20.sol";

/// @notice Shared fixture: a factory and one live vault, wired the way the fork deployment wires
///         them — 6-decimal base asset, an 18-decimal holding priced by an 8-decimal feed.
/// @dev Entirely mock-based on purpose. `forge test` has to pass with no network on a fresh macOS
///      clone at handoff; anything needing real Base state lives in `test/fork/`.
abstract contract VaultTestBase is Test {
    MockERC20 internal usdc;
    MockERC20 internal weth;
    MockAggregatorV3 internal ethFeed;
    CallTarget internal venue;

    VaultFactory internal factory;
    CuratedVault internal vault;

    address internal platform = makeAddr("platform");
    address internal agent = makeAddr("agent");
    address internal guardian = makeAddr("guardian");
    address internal alice = makeAddr("alice");
    address internal bob = makeAddr("bob");

    uint256 internal constant PRICE_MAX_AGE = 3600;
    int256 internal constant ETH_USD = 3000e8;
    bytes32 internal constant MANDATE_HASH = keccak256("mandate-v1");

    function setUp() public virtual {
        // Real-looking wall clock. Foundry starts at timestamp 1, which would make every staleness
        // bound trivially satisfied and hide the very bug the bound exists to catch.
        vm.warp(1_700_000_000);

        usdc = new MockERC20("USD Coin", "USDC", 6);
        weth = new MockERC20("Wrapped Ether", "WETH", 18);
        ethFeed = new MockAggregatorV3(8, "ETH / USD", ETH_USD);
        venue = new CallTarget();

        address[] memory targets = new address[](3);
        targets[0] = address(venue);
        targets[1] = address(usdc);
        targets[2] = address(weth);

        ICuratedVault.TokenValuation[] memory valuations = new ICuratedVault.TokenValuation[](1);
        valuations[0] = ICuratedVault.TokenValuation({token: address(weth), feed: address(ethFeed)});

        factory = new VaultFactory(platform, targets, valuations, PRICE_MAX_AGE);
        vault = CuratedVault(factory.createVault(_createParams()));
    }

    function _createParams() internal view returns (IVaultFactory.CreateParams memory) {
        return IVaultFactory.CreateParams({
            asset: address(usdc),
            name: "Curated USDC",
            symbol: "cUSDC",
            agent: agent,
            guardian: guardian,
            mandateHash: MANDATE_HASH
        });
    }

    /// @notice Fund `who` with USDC and deposit it into the vault on their behalf.
    function _deposit(address who, uint256 assets) internal returns (uint256 shares) {
        usdc.mint(who, assets);
        vm.startPrank(who);
        usdc.approve(address(vault), assets);
        shares = vault.deposit(assets, who);
        vm.stopPrank();
    }

    /// @notice Simulate a completed rebalance: the vault spent USDC and now holds WETH.
    /// @dev Mints rather than swapping — the swap itself is Lane D's concern, and what this suite
    ///      needs to check is that mixed holdings price correctly.
    function _simulateRotation(uint256 usdcOut, uint256 wethIn) internal {
        usdc.burn(address(vault), usdcOut);
        weth.mint(address(vault), wethIn);
    }
}
