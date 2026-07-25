// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import { Test } from "forge-std/Test.sol";
import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import { IAqua } from "@1inch/aqua/src/interfaces/IAqua.sol";

import { SwapVMProgramBuilder } from "../src/SwapVMProgramBuilder.sol";

/**
 * @title AquaShipFork
 * @notice Executes our strategy against the **real deployed Aqua contract** on
 *         a Base mainnet fork.
 *
 * @dev Everything else in this lane proves we *build* correct calldata. This
 *      proves the calldata is *accepted* — by 1inch's live contract, at its
 *      real address, with real token approvals. Without it, the first time we
 *      would learn our encoding is wrong is the mainnet demo.
 *
 *      It also verifies the property the whole 1inch integration rests on:
 *      **shipping moves no tokens.** The maker's balance is asserted unchanged
 *      across `ship()`. That is our locked Pattern 1 custody decision holding
 *      against the real registry rather than against our own description of it.
 *
 *      Run with:
 *        forge test --match-contract AquaShipFork --fork-url $BASE_RPC_URL
 *      Skips itself when no fork URL is available, so the default suite stays
 *      green offline.
 */
contract AquaShipForkTest is Test {
    IAqua internal constant AQUA = IAqua(0x499943E74FB0cE105688beeE8Ef2ABec5D936d31);
    address internal constant SWAPVM = 0x8fDD04Dbf6111437B44bbca99C28882434e0958f;

    IERC20 internal constant USDC = IERC20(0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913);
    IERC20 internal constant WETH = IERC20(0x4200000000000000000000000000000000000006);

    // WETH (0x4200…) sorts below USDC (0x8335…). See SwapVMProgramBuilder.t.sol.
    address internal constant TOKEN_A = address(WETH);
    address internal constant TOKEN_B = address(USDC);

    uint256 internal constant WETH_AMOUNT = 3 ether;
    uint256 internal constant USDC_AMOUNT = 10_000e6;
    uint32 internal constant FEE_BPS = 30;
    uint256 internal constant SALT = 0xC0FFEE;

    SwapVMProgramBuilder internal builder;
    address internal vault; // stands in for Lane A's CuratedVault: the Aqua maker

    function setUp() public {
        string memory rpc = vm.envOr("BASE_RPC_URL", string("https://mainnet.base.org"));
        try vm.createSelectFork(rpc) {
            // forked
        } catch {
            vm.skip(true);
        }

        builder = new SwapVMProgramBuilder();
        vault = makeAddr("curated-vault");

        deal(address(WETH), vault, WETH_AMOUNT);
        deal(address(USDC), vault, USDC_AMOUNT);
    }

    function test_realAquaIsDeployedAtTheDocumentedAddress() public view {
        assertGt(address(AQUA).code.length, 0, "Aqua not deployed at the documented address");
        assertGt(SWAPVM.code.length, 0, "SwapVM not deployed at the documented address");
    }

    /// @dev The headline test: our strategy is accepted by the live registry,
    ///      and the hash it returns is the one we computed off-chain.
    function test_shipIsAcceptedByRealAquaAndHashMatchesOurs() public {
        (bytes memory strategy, bytes32 expectedHash,,) =
            builder.buildStrategySorted(vault, TOKEN_A, TOKEN_B, FEE_BPS, SALT);

        address[] memory tokens = new address[](2);
        tokens[0] = TOKEN_A;
        tokens[1] = TOKEN_B;
        uint256[] memory amounts = new uint256[](2);
        amounts[0] = WETH_AMOUNT;
        amounts[1] = USDC_AMOUNT;

        vm.startPrank(vault);
        WETH.approve(address(AQUA), WETH_AMOUNT);
        USDC.approve(address(AQUA), USDC_AMOUNT);
        bytes32 strategyHash = AQUA.ship(SWAPVM, strategy, tokens, amounts);
        vm.stopPrank();

        // The hash Python records for a later dock() must be the real one.
        assertEq(strategyHash, expectedHash, "on-chain strategy hash differs from ours");
    }

    /// @dev The custody invariant, asserted against the real contract rather
    ///      than against our description of it. If this ever fails, Aqua is not
    ///      the venue we think it is and Pattern 1 is broken.
    function test_shipMovesNoTokensOutOfTheVault() public {
        uint256 wethBefore = WETH.balanceOf(vault);
        uint256 usdcBefore = USDC.balanceOf(vault);

        _ship();

        assertEq(WETH.balanceOf(vault), wethBefore, "WETH left the vault - Pattern 1 violated");
        assertEq(USDC.balanceOf(vault), usdcBefore, "USDC left the vault - Pattern 1 violated");
        assertEq(WETH.balanceOf(address(AQUA)), 0, "Aqua should custody nothing");
    }

    /// @dev Virtual balances are what a taker fills against, so they are the
    ///      evidence the position is actually live.
    function test_virtualBalancesReflectTheShippedAmounts() public {
        bytes32 strategyHash = _ship();

        (uint256 balanceA, uint256 balanceB) =
            AQUA.safeBalances(vault, SWAPVM, strategyHash, TOKEN_A, TOKEN_B);

        assertEq(balanceA, WETH_AMOUNT, "WETH virtual balance wrong");
        assertEq(balanceB, USDC_AMOUNT, "USDC virtual balance wrong");
    }

    /// @dev Closing the position is equally capital-neutral: there is nothing
    ///      to withdraw because nothing ever left.
    function test_dockClearsBalancesAndStillMovesNoTokens() public {
        bytes32 strategyHash = _ship();
        uint256 wethBefore = WETH.balanceOf(vault);

        address[] memory tokens = new address[](2);
        tokens[0] = TOKEN_A;
        tokens[1] = TOKEN_B;

        vm.prank(vault);
        AQUA.dock(SWAPVM, strategyHash, tokens);

        assertEq(WETH.balanceOf(vault), wethBefore, "dock should move no tokens");

        // Balances are cleared, so the strategy is no longer fillable. Aqua
        // reverts rather than reporting zero for a non-active strategy.
        vm.expectRevert();
        AQUA.safeBalances(vault, SWAPVM, strategyHash, TOKEN_A, TOKEN_B);
    }

    function _ship() internal returns (bytes32 strategyHash) {
        (bytes memory strategy,,,) =
            builder.buildStrategySorted(vault, TOKEN_A, TOKEN_B, FEE_BPS, SALT);

        address[] memory tokens = new address[](2);
        tokens[0] = TOKEN_A;
        tokens[1] = TOKEN_B;
        uint256[] memory amounts = new uint256[](2);
        amounts[0] = WETH_AMOUNT;
        amounts[1] = USDC_AMOUNT;

        vm.startPrank(vault);
        WETH.approve(address(AQUA), WETH_AMOUNT);
        USDC.approve(address(AQUA), USDC_AMOUNT);
        strategyHash = AQUA.ship(SWAPVM, strategy, tokens, amounts);
        vm.stopPrank();
    }
}
