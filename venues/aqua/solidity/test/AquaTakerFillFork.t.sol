// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import { Test } from "forge-std/Test.sol";
import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import { IAqua } from "@1inch/aqua/src/interfaces/IAqua.sol";
import { ISwapVM } from "@1inch/swap-vm/src/interfaces/ISwapVM.sol";
import { TakerTraitsLib } from "@1inch/swap-vm/src/libs/TakerTraits.sol";

import { SwapVMProgramBuilder } from "../src/SwapVMProgramBuilder.sol";
import { MockAgentVault } from "./VaultRelayFork.t.sol";

/**
 * @title AquaTakerFillFork
 * @notice **The token transfer.** A third-party taker fills the vault's Aqua
 *         position on a Base mainnet fork, against the real deployed Aqua and
 *         SwapVM contracts.
 *
 * @dev Why this test is the one that closes the 1inch gate.
 *
 *      `Aqua.ship()` deliberately moves **no tokens** — that is the entire
 *      point of virtual balances, and it is what makes Aqua compatible with our
 *      Pattern 1 custody decision. But it also means a ship alone does not
 *      satisfy 1inch's *"onchain execution of token transfers must be presented
 *      during demo"*. Shipping is an accounting entry.
 *
 *      The transfer happens on the **fill**. When a taker swaps against the
 *      position, `SwapVM` calls `AQUA.pull(maker, …)`, which performs a real
 *      ERC-20 transfer out of the maker's wallet — the vault's — and the
 *      taker's input lands back in the vault via `AQUA.push`. Two real
 *      transfers, both visible on-chain, and the vault ends up holding a
 *      different mix of tokens plus a fee it did not have before.
 *
 *      That is also the only thing in this project that shows the vault
 *      *earning* as a market maker rather than merely holding a position.
 *
 * @dev ⚠️ **CURRENTLY SKIPPED — the deployed opcode table does not match any
 *      published swap-vm source, and this test is what found that out.**
 *
 *      SwapVM opcodes are not constants: they are *positions* in
 *      `AquaOpcodes._opcodes()`. Our builder derives them from 1inch's own
 *      instruction table (never hardcoded), and against the pinned v1.0.1
 *      source that yields swap=17, salt=20, flatFee=21.
 *
 *      The contract deployed on Base disagrees. Probed empirically against it:
 *      a program of `[17,0][20,32,salt]` reverts with
 *      `DecayShouldBeCalledBeforeSwapAmountsComputation`, i.e. the deployed VM
 *      reads index 20 as **Decay**, not Salt. In v1.0.1's table Decay is 19.
 *      So the deployed table carries one more entry ahead of Decay than any
 *      tag we can see, and no index we probed produced a real constant-product
 *      quote — every one returned `amountOut == amountIn`, the VM's
 *      pass-through default, meaning no pricing instruction ran.
 *
 *      **What this does and does not invalidate.** Everything verified in
 *      `AquaShipFork` and `VaultRelayFork` still holds — those exercise Aqua
 *      itself (ship, dock, virtual balances, custody, contract-maker support),
 *      and Aqua stores the strategy as opaque bytes without interpreting it.
 *      What is *not* verified is that the **program prices correctly when
 *      executed by the deployed SwapVM**. A position could be shipped, look
 *      healthy, and misprice on fill.
 *
 *      **Next step for whoever picks this up:** get the exact deployed source
 *      or ABI from 1inch (ask at the venue — this is a five-minute question for
 *      someone on their team and hours of probing otherwise), confirm the
 *      instruction table, then delete the `vm.skip` below. Do not guess the
 *      indices: a wrong opcode is a silently mispriced position, which is worse
 *      than no position.
 */
contract AquaTakerFillForkTest is Test {
    IAqua internal constant AQUA = IAqua(0x499943E74FB0cE105688beeE8Ef2ABec5D936d31);
    ISwapVM internal constant SWAPVM = ISwapVM(0x8fDD04Dbf6111437B44bbca99C28882434e0958f);

    IERC20 internal constant USDC = IERC20(0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913);
    IERC20 internal constant WETH = IERC20(0x4200000000000000000000000000000000000006);

    // WETH (0x4200…) sorts below USDC (0x8335…), so it is tokenA.
    address internal constant TOKEN_A = address(WETH);
    address internal constant TOKEN_B = address(USDC);

    uint256 internal constant WETH_SHIPPED = 3 ether;
    uint256 internal constant USDC_SHIPPED = 10_000e6;
    uint32 internal constant FEE_BPS = 30; // 0.30%, the vault's maker fee
    uint256 internal constant SALT = 0xFEED;

    uint256 internal constant TAKER_SPEND = 1_000e6; // taker sells 1,000 USDC

    SwapVMProgramBuilder internal builder;
    MockAgentVault internal vault;
    ISwapVM.Order internal order;
    bytes32 internal strategyHash;

    address internal taker;

    function setUp() public {
        string memory rpc = vm.envOr("BASE_RPC_URL", string("https://mainnet.base.org"));
        try vm.createSelectFork(rpc) {
            // forked
        } catch {
            vm.skip(true);
        }

        // See the contract-level note: the deployed opcode table does not match
        // any published source, so the program cannot yet be priced correctly by
        // the real VM. Skipping keeps the suite honest — this is a known open
        // question, not a passing claim.
        vm.skip(true);

        builder = new SwapVMProgramBuilder(address(AQUA));

        address[] memory targets = new address[](3);
        targets[0] = address(AQUA);
        targets[1] = TOKEN_A;
        targets[2] = TOKEN_B;
        vault = new MockAgentVault(targets);

        deal(address(WETH), address(vault), WETH_SHIPPED);
        deal(address(USDC), address(vault), USDC_SHIPPED);

        _shipPosition();

        taker = makeAddr("third-party-taker");
        deal(address(USDC), taker, TAKER_SPEND);
        vm.prank(taker);
        USDC.approve(address(SWAPVM), type(uint256).max);
    }

    /// @dev Exactly the plan `AquaVenue.plan()` emits, relayed through the vault.
    function _shipPosition() internal {
        bytes memory strategy;
        (strategy, strategyHash,,) =
            builder.buildStrategySorted(address(vault), TOKEN_A, TOKEN_B, FEE_BPS, SALT);
        order = abi.decode(strategy, (ISwapVM.Order));

        address[] memory tokens = new address[](2);
        tokens[0] = TOKEN_A;
        tokens[1] = TOKEN_B;
        uint256[] memory amounts = new uint256[](2);
        amounts[0] = WETH_SHIPPED;
        amounts[1] = USDC_SHIPPED;

        MockAgentVault.Call[] memory calls = new MockAgentVault.Call[](3);
        calls[0] = MockAgentVault.Call({
            target: TOKEN_A,
            value: 0,
            data: abi.encodeCall(IERC20.approve, (address(AQUA), WETH_SHIPPED))
        });
        calls[1] = MockAgentVault.Call({
            target: TOKEN_B,
            value: 0,
            data: abi.encodeCall(IERC20.approve, (address(AQUA), USDC_SHIPPED))
        });
        calls[2] = MockAgentVault.Call({
            target: address(AQUA),
            value: 0,
            data: abi.encodeCall(IAqua.ship, (address(SWAPVM), strategy, tokens, amounts))
        });
        vault.executeBatch(calls);
    }

    /// @dev Taker sells USDC (tokenB) for WETH (tokenA), so the swap runs B→A.
    function _takerData() internal view returns (bytes memory) {
        return TakerTraitsLib.build(
            TakerTraitsLib.Args({
                taker: taker,
                isExactIn: true,
                shouldUnwrapWeth: false,
                isStrictThresholdAmount: false,
                isFirstTransferFromTaker: true,
                // Taker has no Aqua balance of its own, so SwapVM pulls with
                // transferFrom and pushes into the maker's Aqua balance.
                useTransferFromAndAquaPush: true,
                threshold: "",
                to: address(0),
                deadline: 0,
                hasPreTransferInCallback: false,
                hasPreTransferOutCallback: false,
                preTransferInHookData: "",
                postTransferInHookData: "",
                preTransferOutHookData: "",
                postTransferOutHookData: "",
                preTransferInCallbackData: "",
                preTransferOutCallbackData: "",
                instructionsArgs: "",
                signature: ""
            })
        );
    }

    function test_quoteAgainstTheShippedPositionIsNonZero() public view {
        (uint256 amountIn, uint256 amountOut,) =
            SWAPVM.quote(order, TOKEN_B, TOKEN_A, TAKER_SPEND, _takerData());

        assertEq(amountIn, TAKER_SPEND, "exact-in should consume the full amount");
        assertGt(amountOut, 0, "the position should quote a non-zero output");
    }

    /**
     * @dev **The headline.** Real ERC-20 transfers in both directions, out of
     *      and into the vault's own wallet, executed by the real SwapVM against
     *      the real Aqua registry.
     */
    function test_takerFillMovesRealTokensOutOfTheVault() public {
        uint256 vaultWethBefore = WETH.balanceOf(address(vault));
        uint256 vaultUsdcBefore = USDC.balanceOf(address(vault));
        uint256 takerWethBefore = WETH.balanceOf(taker);

        vm.prank(taker);
        (uint256 amountIn, uint256 amountOut,) =
            SWAPVM.swap(order, TOKEN_B, TOKEN_A, TAKER_SPEND, _takerData());

        assertEq(amountIn, TAKER_SPEND);
        assertGt(amountOut, 0, "taker received nothing");

        // WETH really left the vault — this is the transfer 1inch asks to see.
        assertEq(
            WETH.balanceOf(address(vault)),
            vaultWethBefore - amountOut,
            "vault WETH did not decrease by the filled amount"
        );
        assertEq(
            WETH.balanceOf(taker), takerWethBefore + amountOut, "taker did not receive WETH"
        );

        // ...and the taker's USDC really arrived.
        assertEq(
            USDC.balanceOf(address(vault)),
            vaultUsdcBefore + amountIn,
            "vault USDC did not increase by the taker's input"
        );
        assertEq(USDC.balanceOf(taker), 0, "taker USDC was not spent");
    }

    /// @dev The vault is *earning*, not just holding. With a 30 bps maker fee,
    ///      the value it receives exceeds what the pure curve would have given
    ///      away — which is the whole reason to run a maker position at all.
    function test_theVaultEarnsItsMakerFee() public {
        (, uint256 amountOutWithFee,) = SWAPVM.quote(order, TOKEN_B, TOKEN_A, TAKER_SPEND, _takerData());

        // Same position, same size, no fee.
        (bytes memory freeStrategy,,,) =
            builder.buildStrategySorted(address(vault), TOKEN_A, TOKEN_B, 0, SALT + 1);
        ISwapVM.Order memory freeOrder = abi.decode(freeStrategy, (ISwapVM.Order));

        address[] memory tokens = new address[](2);
        tokens[0] = TOKEN_A;
        tokens[1] = TOKEN_B;
        uint256[] memory amounts = new uint256[](2);
        amounts[0] = WETH_SHIPPED;
        amounts[1] = USDC_SHIPPED;
        vault.execute(
            address(AQUA),
            0,
            abi.encodeCall(IAqua.ship, (address(SWAPVM), freeStrategy, tokens, amounts))
        );

        (, uint256 amountOutNoFee,) = SWAPVM.quote(freeOrder, TOKEN_B, TOKEN_A, TAKER_SPEND, _takerData());

        assertLt(
            amountOutWithFee,
            amountOutNoFee,
            "the fee should reduce what the taker gets - that difference is the vault's earnings"
        );
    }

    /// @dev A fill is what turns virtual balances into a changed position. This
    ///      is what the decision feed should eventually show: the vault started
    ///      WETH-heavy and ends USDC-heavier without the agent doing anything.
    function test_fillRebalancesTheVirtualBalances() public {
        (uint256 wethBefore, uint256 usdcBefore) =
            AQUA.safeBalances(address(vault), address(SWAPVM), strategyHash, TOKEN_A, TOKEN_B);

        vm.prank(taker);
        SWAPVM.swap(order, TOKEN_B, TOKEN_A, TAKER_SPEND, _takerData());

        (uint256 wethAfter, uint256 usdcAfter) =
            AQUA.safeBalances(address(vault), address(SWAPVM), strategyHash, TOKEN_A, TOKEN_B);

        assertLt(wethAfter, wethBefore, "WETH virtual balance should fall");
        assertGt(usdcAfter, usdcBefore, "USDC virtual balance should rise");
    }

    /// @dev Custody, restated where it is least obvious. Tokens *do* move on a
    ///      fill — but only as the settlement of a trade the vault agreed to by
    ///      posting the curve. The vault is never not the owner of what it
    ///      holds, and no third party can move funds except by trading against
    ///      the published strategy at its own price.
    function test_onlyTheShippedTokensCanEverMove() public {
        // Give the vault an unrelated holding that is not part of the strategy.
        deal(address(WETH), address(vault), WETH_SHIPPED + 5 ether);
        uint256 untouchable = WETH.balanceOf(address(vault)) - WETH_SHIPPED;

        vm.prank(taker);
        (, uint256 amountOut,) = SWAPVM.swap(order, TOKEN_B, TOKEN_A, TAKER_SPEND, _takerData());

        assertLe(
            amountOut, WETH_SHIPPED, "a fill must never exceed the shipped virtual balance"
        );
        assertGe(
            WETH.balanceOf(address(vault)),
            untouchable,
            "holdings outside the strategy must be untouchable"
        );
    }
}
