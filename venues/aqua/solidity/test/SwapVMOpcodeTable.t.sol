// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import { Test, console } from "forge-std/Test.sol";
import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import { IAqua } from "@1inch/aqua/src/interfaces/IAqua.sol";
import { ISwapVM } from "@1inch/swap-vm/src/interfaces/ISwapVM.sol";
import { MakerTraitsLib } from "@1inch/swap-vm/src/libs/MakerTraits.sol";

import { DeployedTakerTraits } from "./DeployedTakerTraits.sol";
import { MockAgentVault } from "./VaultRelayFork.t.sol";

/**
 * @title SwapVMOpcodeTable
 * @notice Reads the **deployed** SwapVM instruction table off Base, one opcode
 *         at a time, and pins the three indices our strategy programs depend on.
 *
 * @dev Why this test exists.
 *
 *      SwapVM opcodes are not constants. They are *positions* in
 *      `AquaOpcodes._opcodes()`, and that array is built by a trick worth
 *      understanding before reading anything below:
 *
 *      ```solidity
 *      function(...) internal[35] memory instructions = [ _notInstruction, ... ];
 *      assembly { result := instructions; mstore(result, 34) }
 *      ```
 *
 *      A fixed-size memory array has no length prefix; a dynamic one does. So
 *      writing the length **over `instructions[0]`** turns the static array into
 *      a dynamic array whose element 0 is the old element 1. Every opcode is
 *      therefore its source-array position **minus one**. Against our pinned
 *      v1.0.1 that yields swap = 17, salt = 20, flatFee = 21.
 *
 *      The contract deployed on Base does not agree, and
 *      `AquaTakerFillFork.t.sol` was skipped for a whole wave because of it: a
 *      program of `[17,0][20,32,salt]` reverts with
 *      `DecayShouldBeCalledBeforeSwapAmountsComputation`, so the deployed VM
 *      reads 20 as **Decay** where v1.0.1 has Salt.
 *
 *      Guessing the offset from one revert is how a position ends up silently
 *      mispriced, which is strictly worse than having no position. So this
 *      reads the table instead of inferring it.
 *
 * @dev How the read works — every instruction fingerprints itself.
 *
 *      Almost every SwapVM instruction parses its arguments before doing
 *      anything else, and reverts with an error naming *itself* when they are
 *      missing: `JumpMissingNextPCArg`, `ControlsMissingTokenArg`,
 *      `DecayMissingPeriodArg`, `FeeMissingFeeBPS`, `ConcentrateMissingSqrtPriceMin`.
 *      Shipping a one-instruction program `[i, 0]` — opcode `i`, zero args —
 *      and recording the revert selector therefore *names* the instruction at
 *      index `i`.
 *
 *      Two instructions take no arguments and so cannot miss any. They identify
 *      themselves by succeeding instead:
 *        - `XYCSwap._xycSwapXD` returns a constant-product quote, which we check
 *          against the arithmetic rather than merely observing "no revert";
 *        - `Controls._salt` is a no-op, leaving `amountOut == 0`.
 *
 *      That distinction matters: the pass-through default of an empty program
 *      also produces no revert, and mistaking it for a working swap is exactly
 *      the failure mode that kept the taker fill skipped.
 */
contract SwapVMOpcodeTableTest is Test {
    IAqua internal constant AQUA = IAqua(0x499943E74FB0cE105688beeE8Ef2ABec5D936d31);
    ISwapVM internal constant SWAPVM = ISwapVM(0x8fDD04Dbf6111437B44bbca99C28882434e0958f);

    IERC20 internal constant USDC = IERC20(0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913);
    IERC20 internal constant WETH = IERC20(0x4200000000000000000000000000000000000006);

    // WETH (0x4200…) sorts below USDC (0x8335…), so it is tokenA.
    address internal constant TOKEN_A = address(WETH);
    address internal constant TOKEN_B = address(USDC);

    uint256 internal constant WETH_SHIPPED = 3 ether;
    uint256 internal constant USDC_SHIPPED = 10_000e6;
    uint256 internal constant TAKER_SPEND = 1_000e6;

    /// @dev The highest index worth probing. v1.0.1's table is 34 long; going
    ///      past it costs nothing and proves where the deployed table ends.
    uint256 internal constant MAX_OPCODE = 40;

    MockAgentVault internal vault;
    address internal taker;

    function setUp() public {
        string memory rpc = vm.envOr("BASE_RPC_URL", string("https://mainnet.base.org"));
        try vm.createSelectFork(rpc) {
            // forked
        } catch {
            vm.skip(true);
        }

        address[] memory targets = new address[](3);
        targets[0] = address(AQUA);
        targets[1] = TOKEN_A;
        targets[2] = TOKEN_B;
        vault = new MockAgentVault(targets);

        // Generous, because every probe ships its own position against the same
        // wallet. Aqua records virtual balances and moves nothing, so the same
        // tokens can back many strategies at once — see the note in `#17`.
        deal(address(WETH), address(vault), WETH_SHIPPED * 100);
        deal(address(USDC), address(vault), USDC_SHIPPED * 100);

        vault.execute(TOKEN_A, 0, abi.encodeCall(IERC20.approve, (address(AQUA), type(uint256).max)));
        vault.execute(TOKEN_B, 0, abi.encodeCall(IERC20.approve, (address(AQUA), type(uint256).max)));

        taker = makeAddr("opcode-probe-taker");
    }

    // ── probing machinery ────────────────────────────────────────────────

    /// @dev A single-instruction program: opcode `i`, zero arguments.
    function _probeProgram(uint8 opcode) internal pure returns (bytes memory) {
        return abi.encodePacked(opcode, uint8(0));
    }

    function _order(bytes memory program) internal view returns (ISwapVM.Order memory) {
        return MakerTraitsLib.build(
            MakerTraitsLib.Args({
                maker: address(vault),
                receiver: address(0),
                shouldUnwrapWeth: false,
                useAquaInsteadOfSignature: true,
                allowZeroAmountIn: false,
                hasPreTransferInHook: false,
                hasPostTransferInHook: false,
                hasPreTransferOutHook: false,
                hasPostTransferOutHook: false,
                preTransferInTarget: address(0),
                preTransferInData: "",
                postTransferInTarget: address(0),
                postTransferInData: "",
                preTransferOutTarget: address(0),
                preTransferOutData: "",
                postTransferOutTarget: address(0),
                postTransferOutData: "",
                program: program
            })
        );
    }

    function _ship(ISwapVM.Order memory order) internal {
        bytes memory strategy = abi.encode(order);

        address[] memory tokens = new address[](2);
        tokens[0] = TOKEN_A;
        tokens[1] = TOKEN_B;
        uint256[] memory amounts = new uint256[](2);
        amounts[0] = WETH_SHIPPED;
        amounts[1] = USDC_SHIPPED;

        vault.execute(
            address(AQUA), 0, abi.encodeCall(IAqua.ship, (address(SWAPVM), strategy, tokens, amounts))
        );
    }

    function _takerData() internal pure returns (bytes memory) {
        return DeployedTakerTraits.simpleFill({ isExactIn: true });
    }

    /// @dev Ship a one-instruction position and quote against it.
    /// @return ok        Whether the quote returned rather than reverted.
    /// @return amountOut The quoted output when `ok`.
    /// @return selector  The revert selector when not `ok`.
    function _probe(uint8 opcode) internal returns (bool ok, uint256 amountOut, bytes4 selector) {
        ISwapVM.Order memory order = _order(_probeProgram(opcode));
        _ship(order);

        try SWAPVM.quote(order, TOKEN_B, TOKEN_A, TAKER_SPEND, _takerData()) returns (
            uint256, uint256 out, bytes32
        ) {
            return (true, out, bytes4(0));
        } catch (bytes memory err) {
            return (false, 0, err.length >= 4 ? bytes4(err) : bytes4(0));
        }
    }

    // ── the read ─────────────────────────────────────────────────────────

    /**
     * @notice Dumps the deployed instruction table. Informational by design —
     *         it asserts nothing, so it cannot fail for the wrong reason. The
     *         assertions live in the tests below, which depend on what this
     *         prints.
     * @dev Run with `-vv` to see it. Selectors are resolved to names by
     *      `scripts/decode-swapvm-opcodes.py`, which computes them from the
     *      swap-vm sources rather than from a hand-typed list.
     */
    function test_probeTheDeployedInstructionTable() public {
        console.log("idx | result");
        for (uint256 i = 0; i <= MAX_OPCODE; i++) {
            (bool ok, uint256 amountOut, bytes4 selector) = _probe(uint8(i));
            if (ok) {
                console.log(string.concat("  ", vm.toString(i), " | OK amountOut="), amountOut);
            } else {
                console.log(string.concat("  ", vm.toString(i), " | REVERT "), vm.toString(selector));
            }
        }
    }

    /**
     * @notice The constant-product identification, stated as arithmetic.
     * @dev `amountOut = amountIn · balanceOut / (balanceIn + amountIn)` with
     *      floor division — `XYCSwap._xycSwapXD` verbatim. An index that
     *      reproduces this is the swap instruction, and nothing else in the
     *      table can.
     *
     *      Checking the *number* rather than merely "it did not revert" is what
     *      makes this identification rather than a guess. Under the package's
     *      taker-traits encoding this same call returned a perfectly plausible
     *      `amountOut` of exactly `amountIn` — the exact-output answer, because
     *      the `isExactIn` flag had silently cleared. See `DeployedTakerTraits`.
     */
    function _isConstantProduct(uint256 amountOut) internal pure returns (bool) {
        uint256 expected = (TAKER_SPEND * WETH_SHIPPED) / (USDC_SHIPPED + TAKER_SPEND);
        return amountOut == expected;
    }

    // ── the guard ────────────────────────────────────────────────────────

    // Fingerprints observed on the deployed contract, each matched to a name by
    // `decode_swapvm_opcodes.py` against that contract's own verified source.
    bytes4 internal constant NOTHING_COMPUTED = 0xf6ab88ca; // TakerTraitsAmountOutMustBeGreaterThanZero
    bytes4 internal constant JUMP_ARG = 0xa154e5d9; // JumpMissingNextPCArg
    bytes4 internal constant TOKEN_ARG = 0x6cac7aec; // ControlsMissingTokenArg
    bytes4 internal constant DEADLINE_ARG = 0x05d37ba1; // ControlsMissingDeadlineArg
    bytes4 internal constant CONCENTRATE_XD = 0xfd7d16b0; // ConcentrateParsingMissingTokensCount
    bytes4 internal constant CONCENTRATE_2D = 0xec286c06; // ConcentrateTwoTokensMissingDeltaLt
    bytes4 internal constant DECAY_ARG = 0x9d584cd8; // DecayMissingPeriodArg
    bytes4 internal constant FEE_ARG = 0xa73c6824; // FeeMissingFeeBPS
    bytes4 internal constant PROGRESSIVE_FEE_ARG = 0x4f5033b3; // ProgressiveFeeMissingFeeBPS
    bytes4 internal constant PROTOCOL_FEE_ARG = 0xeb9dadfd; // ProtocolFeeMissingFeeBPS
    bytes4 internal constant PANIC = 0x4e487b71; // Panic(uint256) — index past the table

    /// @dev The three we actually emit. Nothing in `venues/` hardcodes these;
    ///      they are what `DeployedAquaOpcodes` resolves to, asserted here
    ///      against the chain so the transcription cannot rot unnoticed.
    uint8 internal constant OPCODE_XYC_SWAP = 17;
    uint8 internal constant OPCODE_SALT = 21;
    uint8 internal constant OPCODE_FLAT_FEE_IN = 22;

    /**
     * @notice The deployed table, asserted entry by entry.
     * @dev This is the guard that request #29 needed and did not have. If 1inch
     *      redeploys SwapVM with a reordered table, this fails here — loudly,
     *      in CI, naming the index — instead of silently mispricing a live
     *      maker position, which is the failure mode that cost this lane a
     *      wave. `ship()` never executes the program, so there is no earlier
     *      point at which a wrong opcode can be caught.
     */
    function test_theDeployedTableIsWhatWeTranscribed() public {
        bytes4[28] memory expected = [
            // 0–9: the reserved debug slots. A no-op leaves `amountOut` at zero,
            // so the run loop rejects the quote rather than the instruction.
            NOTHING_COMPUTED, NOTHING_COMPUTED, NOTHING_COMPUTED, NOTHING_COMPUTED, NOTHING_COMPUTED,
            NOTHING_COMPUTED, NOTHING_COMPUTED, NOTHING_COMPUTED, NOTHING_COMPUTED, NOTHING_COMPUTED,
            JUMP_ARG, // 10  Controls._jump
            TOKEN_ARG, // 11  Controls._jumpIfTokenIn
            TOKEN_ARG, // 12  Controls._jumpIfTokenOut
            DEADLINE_ARG, // 13  Controls._deadline
            TOKEN_ARG, // 14  Controls._onlyTakerTokenBalanceNonZero
            TOKEN_ARG, // 15  Controls._onlyTakerTokenBalanceGte
            TOKEN_ARG, // 16  Controls._onlyTakerTokenSupplyShareGte
            bytes4(0), // 17  XYCSwap._xycSwapXD — succeeds; checked separately
            CONCENTRATE_XD, // 18  the entry v1.0.1 does not have at all
            CONCENTRATE_2D, // 19  XYCConcentrate._xycConcentrateGrowLiquidity2D
            DECAY_ARG, // 20  Decay._decayXD
            NOTHING_COMPUTED, // 21  Controls._salt — a no-op by design
            FEE_ARG, // 22  Fee._flatFeeAmountInXD
            FEE_ARG, // 23  Fee._flatFeeAmountOutXD
            PROGRESSIVE_FEE_ARG, // 24  Fee._progressiveFeeInXD
            PROGRESSIVE_FEE_ARG, // 25  Fee._progressiveFeeOutXD
            PROTOCOL_FEE_ARG, // 26  Fee._protocolFeeAmountOutXD
            PROTOCOL_FEE_ARG // 27  Fee._aquaProtocolFeeAmountOutXD
        ];

        for (uint256 i = 0; i < expected.length; i++) {
            (bool ok, uint256 amountOut, bytes4 selector) = _probe(uint8(i));
            if (i == OPCODE_XYC_SWAP) {
                assertTrue(ok, "opcode 17 should quote, not revert");
                assertTrue(_isConstantProduct(amountOut), "opcode 17 is not the constant-product swap");
            } else {
                assertFalse(ok, string.concat("opcode ", vm.toString(i), " unexpectedly succeeded"));
                assertEq(
                    selector, expected[i], string.concat("opcode ", vm.toString(i), " is not the instruction we expect")
                );
            }
        }
    }

    /// @notice The table ends where we think it ends.
    /// @dev Its *length* fixes every opcode, because the length word is written
    ///      over element zero. Reading one past the end panics with array
    ///      out-of-bounds, which dates the deployed build independently of its
    ///      source: v1.0.1's table is 34 long, this one is 28.
    function test_theTableEndsAt28Entries() public {
        (,, bytes4 lastValid) = _probe(27);
        assertTrue(lastValid != PANIC, "27 should be a real instruction");

        (,, bytes4 pastEnd) = _probe(28);
        assertEq(pastEnd, PANIC, "28 should be past the end of the deployed table");
    }

    /**
     * @notice The three opcodes our strategy programs actually emit.
     * @dev Stated as a table so the off-by-one that caused #29 is legible:
     *      compiling against the npm package resolves salt to 20 and the flat
     *      fee to 21, and the deployed VM reads 20 as **Decay**.
     */
    function test_theOpcodesWeEmitAreTheOnesTheDeployedVMRuns() public {
        (bool swapOk, uint256 amountOut,) = _probe(OPCODE_XYC_SWAP);
        assertTrue(swapOk && _isConstantProduct(amountOut), "XYCSwap is not at 17");

        (bool saltOk,, bytes4 saltSelector) = _probe(OPCODE_SALT);
        assertFalse(saltOk, "salt should not price anything on its own");
        assertEq(saltSelector, NOTHING_COMPUTED, "opcode 21 is not the no-op Salt");

        (,, bytes4 feeSelector) = _probe(OPCODE_FLAT_FEE_IN);
        assertEq(feeSelector, FEE_ARG, "opcode 22 is not Fee._flatFeeAmountInXD");
    }
}
