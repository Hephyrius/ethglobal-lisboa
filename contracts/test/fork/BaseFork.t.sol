// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";

import {CuratedVault} from "../../src/CuratedVault.sol";
import {VaultFactory} from "../../src/VaultFactory.sol";
import {IAggregatorV3} from "../../src/interfaces/IAggregatorV3.sol";
import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";
import {IVaultFactory} from "../../src/interfaces/IVaultFactory.sol";

/// @notice The vault against real Base mainnet state: real USDC, real WETH, a real Chainlink feed
///         and the real venue contracts the agent will call.
///
/// @dev **Skips itself when there is no RPC.** The unit suite is mock-based and must stay green on a
///      fresh macOS clone at handoff, where `BASE_RPC_URL` may not exist yet. A fork suite that hard
///      failed in that situation would make `forge test` useless as a smoke check.
///
///      Run with: `forge test --match-path "test/fork/*"` and `BASE_RPC_URL` set — or point it at a
///      running `scripts/anvil-fork.sh` via `ANVIL_RPC_URL`, which is cheaper on rate limits because
///      anvil caches forked state locally.
contract BaseForkTest is Test {
    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant WETH = 0x4200000000000000000000000000000000000006;
    address internal constant AQUA = 0x499943E74FB0cE105688beeE8Ef2ABec5D936d31;
    address internal constant SWAPVM = 0x8fDD04Dbf6111437B44bbca99C28882434e0958f;
    address internal constant PERMIT2 = 0x000000000022D473030F116dDEE9F6B43aC78BA3;
    address internal constant UNIVERSAL_ROUTER = 0x6fF5693b99212Da76ad316178A184AB56D299b43;
    address internal constant ETH_USD_FEED = 0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70;

    VaultFactory internal factory;
    CuratedVault internal vault;

    address internal platform = makeAddr("platform");
    address internal agent = makeAddr("agent");
    address internal guardian = makeAddr("guardian");
    address internal alice = makeAddr("alice");

    bool internal live;

    function setUp() public {
        string memory rpc = vm.envOr("ANVIL_RPC_URL", vm.envOr("BASE_RPC_URL", string("")));
        if (bytes(rpc).length == 0) return;

        try vm.createSelectFork(rpc) {
            live = true;
        } catch {
            return; // unreachable endpoint is a skip, not a failure
        }

        address[] memory targets = new address[](7);
        targets[0] = AQUA;
        targets[1] = SWAPVM;
        targets[2] = UNIVERSAL_ROUTER;
        targets[3] = PERMIT2;
        targets[4] = USDC;
        targets[5] = WETH;
        targets[6] = 0x2626664c2603336E57B271c5C0b26F421741e481;

        ICuratedVault.TokenValuation[] memory valuations = new ICuratedVault.TokenValuation[](1);
        valuations[0] = ICuratedVault.TokenValuation({token: WETH, feed: ETH_USD_FEED});

        // priceMaxAge 0: on a pinned fork the feed's `updatedAt` is frozen while block.timestamp
        // advances, so any real bound would fail here for reasons that say nothing about the code.
        factory = new VaultFactory(platform, targets, valuations, 0);
        vault = CuratedVault(
            factory.createVault(
                IVaultFactory.CreateParams({
                    asset: USDC,
                    name: "Curated USDC Vault",
                    symbol: "cUSDC",
                    agent: agent,
                    guardian: guardian,
                    mandateHash: keccak256("fork-mandate"),
                    deployer: address(0)
                })
            )
        );
    }

    modifier onlyLive() {
        if (!live) {
            vm.skip(true);
        }
        _;
    }

    /// @dev Every address in `script/Deploy.s.sol` asserted against live state. A wrong constant
    ///      here is the difference between a working demo and every plan reverting on-chain.
    function test_allowlistedAddressesAreRealContracts() public onlyLive {
        assertGt(AQUA.code.length, 0, "Aqua");
        assertGt(SWAPVM.code.length, 0, "SwapVM");
        assertGt(PERMIT2.code.length, 0, "Permit2");
        assertGt(UNIVERSAL_ROUTER.code.length, 0, "UniversalRouter");
        assertGt(USDC.code.length, 0, "USDC");
        assertGt(WETH.code.length, 0, "WETH");
    }

    function test_realTokenMetadata() public onlyLive {
        assertEq(IERC20Metadata(USDC).symbol(), "USDC", "USDC symbol");
        assertEq(IERC20Metadata(USDC).decimals(), 6, "USDC decimals");
        assertEq(IERC20Metadata(WETH).decimals(), 18, "WETH decimals");
    }

    function test_realChainlinkFeedIsSane() public onlyLive {
        IAggregatorV3 feed = IAggregatorV3(ETH_USD_FEED);
        assertEq(feed.decimals(), 8, "USD feeds are 8-decimal");

        (, int256 answer,, uint256 updatedAt,) = feed.latestRoundData();
        assertGt(answer, 0, "feed is reporting");
        assertGt(updatedAt, 0, "round completed");
        // Wide bounds on purpose: this asserts the feed is a real ETH/USD price, not a specific one.
        // Casts are safe — `answer > 0` is asserted immediately above.
        // forge-lint: disable-next-line(unsafe-typecast)
        assertGt(uint256(answer), 100e8, "ETH above $100");
        // forge-lint: disable-next-line(unsafe-typecast)
        assertLt(uint256(answer), 100_000e8, "ETH below $100,000");
    }

    function test_depositAndRedeemRealUsdc() public onlyLive {
        _fundUsdc(alice, 10_000e6);

        vm.startPrank(alice);
        IERC20(USDC).approve(address(vault), 5_000e6);
        uint256 shares = vault.deposit(5_000e6, alice);
        vm.stopPrank();

        assertEq(shares, 5_000e18, "18-decimal shares over a 6-decimal asset");
        assertEq(vault.totalAssets(), 5_000e6, "totalAssets");
        assertEq(vault.convertToAssets(1e18), 1e6, "one share is worth exactly 1 USDC");
        assertEq(IERC20(USDC).balanceOf(address(vault)), 5_000e6, "vault custodies real USDC");

        vm.prank(alice);
        uint256 out = vault.redeem(shares / 2, alice, alice);

        assertApproxEqAbs(out, 2_500e6, 1, "half out");
        assertEq(IERC20(USDC).balanceOf(alice), 7_500e6, "alice holds real USDC again");
    }

    /// @dev The exact first step of every Uniswap `ExecutionPlan` Lane D produces.
    function test_agentApprovesRealPermit2ThroughTheVault() public onlyLive {
        _fundUsdc(alice, 1_000e6);
        vm.startPrank(alice);
        IERC20(USDC).approve(address(vault), 1_000e6);
        vault.deposit(1_000e6, alice);
        vm.stopPrank();

        vm.prank(agent);
        vault.execute(USDC, 0, abi.encodeCall(IERC20.approve, (PERMIT2, 1_000e6)));

        assertEq(IERC20(USDC).allowance(address(vault), PERMIT2), 1_000e6, "real allowance to real Permit2");
    }

    function test_wethIsPricedThroughTheRealFeed() public onlyLive {
        _fundUsdc(alice, 1_000e6);
        vm.startPrank(alice);
        IERC20(USDC).approve(address(vault), 1_000e6);
        vault.deposit(1_000e6, alice);
        vm.stopPrank();

        deal(WETH, address(vault), 1e18); // one real WETH in the vault

        (, int256 answer,,,) = IAggregatorV3(ETH_USD_FEED).latestRoundData();
        assertGt(answer, 0, "feed is reporting");
        // Cast is safe given the assertion above.
        // forge-lint: disable-next-line(unsafe-typecast)
        uint256 expectedWethValue = uint256(answer) / 100; // 8-decimal USD price -> 6-decimal USDC

        assertApproxEqAbs(
            vault.totalAssets(), 1_000e6 + expectedWethValue, 1, "USDC leg plus WETH leg at the live price"
        );

        ICuratedVault.Holding[] memory h = vault.holdings();
        assertEq(h[0].token, USDC, "base asset first");
        assertEq(h[1].token, WETH, "then the valued token");
        assertEq(h[1].balance, 1e18, "real WETH balance");
        assertApproxEqAbs(h[1].valueInAsset, expectedWethValue, 1, "priced consistently with totalAssets");
    }

    function test_realVenueTargetsAreCallableAndStrangersAreNot() public onlyLive {
        assertTrue(vault.isAllowedTarget(AQUA), "Aqua");
        assertTrue(vault.isAllowedTarget(SWAPVM), "SwapVM");
        assertTrue(vault.isAllowedTarget(UNIVERSAL_ROUTER), "UniversalRouter");
        assertTrue(vault.isAllowedTarget(USDC), "USDC as an approve target");
        assertFalse(vault.isAllowedTarget(address(0xdead)), "a stranger");
    }

    /// @dev The §10 book against **real** USDC, **real** WETH and the **live** ETH/USD feed, rather
    ///      than mocks that could be flattering it. The whole point of `redeemInKind` is that it does
    ///      not depend on what anything is worth, so proving it where the price is genuinely unknown
    ///      at test-authoring time is the version of the claim worth making.
    function test_redeemInKindPaysOutAgainstRealBaseState() public onlyLive {
        _fundUsdc(alice, 15_000e6);
        vm.startPrank(alice);
        IERC20(USDC).approve(address(vault), 15_000e6);
        uint256 shares = vault.deposit(15_000e6, alice);
        vm.stopPrank();

        // A completed rotation: 6,000 USDC of the book is now real WETH, leaving 9,000 liquid.
        (, int256 answer,,,) = IAggregatorV3(ETH_USD_FEED).latestRoundData();
        assertGt(answer, 0, "feed is reporting");
        // forge-lint: disable-next-line(unsafe-typecast)
        uint256 wethIn = (6_000e6 * 1e20) / uint256(answer);
        deal(USDC, address(vault), 9_000e6);
        deal(WETH, address(vault), wethIn);

        assertApproxEqRel(vault.totalAssets(), 15_000e6, 1e15, "solvent at the live price");
        assertEq(IERC20(USDC).balanceOf(address(vault)), 9_000e6, "and only 9,000 of it liquid");

        // The hole: a 15,000 claim against 9,000 of the asset the front door pays in.
        vm.expectRevert();
        vm.prank(alice);
        vault.redeem(shares, alice, alice);

        // The door that needs no market.
        vm.prank(alice);
        ICuratedVault.InKindPayout[] memory payouts = vault.redeemInKind(shares, alice, alice);

        assertEq(vault.balanceOf(alice), 0, "out in full");
        assertEq(payouts[0].token, USDC, "base asset first");

        // Relative, not absolute. What stays behind is the virtual-share offset — a fixed *fraction*
        // of the book, ~10⁻¹⁰ — so on an 18-decimal token it is a few hundred million wei and on a
        // 6-decimal one it rounds away entirely. An absolute wei bound would be an assertion about
        // WETH's decimals dressed as a payout claim, and would have passed for the wrong reason.
        assertApproxEqRel(IERC20(USDC).balanceOf(alice), 9_000e6, 1e9, "took the cash leg");
        assertApproxEqRel(IERC20(WETH).balanceOf(alice), wethIn, 1e9, "and the WETH leg redeem could not reach");
    }

    /// @dev Wind-down against a real venue rather than a mock: the vault genuinely cannot approve
    ///      Permit2 into a *larger* position while paused, and genuinely still can while not.
    function test_windDownBindsAgainstRealBaseState() public onlyLive {
        _fundUsdc(alice, 1_000e6);
        vm.startPrank(alice);
        IERC20(USDC).approve(address(vault), 1_000e6);
        vault.deposit(1_000e6, alice);
        vm.stopPrank();
        deal(WETH, address(vault), 1e18);

        vm.prank(guardian);
        vault.pause();
        assertTrue(vault.paused(), "wind-down is live");

        // Buying real WETH with real USDC through an allowlisted target: refused on direction alone.
        vm.expectRevert(
            abi.encodeWithSelector(ICuratedVault.WindDownWouldSpendBaseAsset.selector, uint256(1_000e6), uint256(0))
        );
        vm.prank(agent);
        vault.execute(USDC, 0, abi.encodeCall(IERC20.transfer, (address(0xdead), 1_000e6)));

        // Approving a real venue still works, because an unwind cannot happen without it.
        vm.prank(agent);
        vault.approveVenue(WETH, PERMIT2, 1e18);
        assertEq(IERC20(WETH).allowance(address(vault), PERMIT2), 1e18, "real allowance to real Permit2");

        // And the exit is open throughout. `balanceOf` is hoisted deliberately: it is an external
        // call, so evaluating it inside the argument list consumes the prank and the redemption
        // arrives from the test contract instead of from alice.
        uint256 aliceShares = vault.balanceOf(alice);
        vm.prank(alice);
        vault.redeemInKind(aliceShares, alice, alice);
        assertGt(IERC20(WETH).balanceOf(alice), 0, "paid in kind from a paused vault");
    }

    /// @dev `deal` on a proxied token can miss the real balance slot, so assert it landed.
    function _fundUsdc(address to, uint256 amount) internal {
        deal(USDC, to, amount);
        assertEq(IERC20(USDC).balanceOf(to), amount, "funding failed - USDC balance slot moved?");
    }
}
