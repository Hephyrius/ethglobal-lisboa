// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import { ISwapVM } from "@1inch/swap-vm/src/interfaces/ISwapVM.sol";
import { MakerTraitsLib } from "@1inch/swap-vm/src/libs/MakerTraits.sol";
import { Fee, FeeArgsBuilder } from "@1inch/swap-vm/src/instructions/Fee.sol";
import { Controls } from "@1inch/swap-vm/src/instructions/Controls.sol";
import { XYCSwap } from "@1inch/swap-vm/src/instructions/XYCSwap.sol";
import { Program, ProgramBuilder } from "@1inch/swap-vm/test/utils/ProgramBuilder.sol";
import { DeployedAquaOpcodes } from "./DeployedAquaOpcodes.sol";

/**
 * @title SwapVMProgramBuilder
 * @notice Compiles SwapVM strategy programs for an Aqua maker position. **Pure
 *         view contract — it holds nothing, moves nothing, and is never called
 *         by the vault.** Deployed once (or run via an `eth_call` state
 *         override) and read off-chain.
 *
 * @dev Why this contract exists, and why it inherits `DeployedAquaOpcodes`.
 *
 *      SwapVM programs are packed bytecode: `opcode ‖ argLength ‖ args`. The
 *      opcode numbers are **not** constants — in the deployed SwapVM they are
 *      *positions in `AquaOpcodes._opcodes()`*, an ordered array of function
 *      pointers. `ProgramBuilder.build` takes the instruction itself and
 *      resolves its index by searching that array.
 *
 *      So this contract inherits an opcode table and passes real function
 *      pointers (`XYCSwap._xycSwapXD`, `Fee._flatFeeAmountInXD`,
 *      `Controls._salt`). Nothing here hardcodes an opcode number; every one is
 *      derived at compile time from the position of its instruction.
 *
 *      **Which table, though, is the entire question.** It inherits
 *      `DeployedAquaOpcodes` — a transcription of the table in the *deployed*
 *      contract's own verified source — and not the npm package's
 *      `AquaOpcodes`, because **no published swap-vm tag matches what is
 *      deployed on Base.** The deployed table carries one instruction v1.0.1
 *      does not have, which pushed `Controls._salt` and
 *      `Fee._flatFeeAmountInXD` each one opcode higher than the package
 *      resolves them to. That was request #29, and it is now closed.
 *
 *      **Neither failure here was theoretical.** An earlier version compiled
 *      against swap-vm `main`, which replaced the positional scheme with a
 *      banked hex enum (`XYCSwap = 0x50`). Those programs encoded cleanly,
 *      shipped into Aqua successfully, and would have been executed by the
 *      deployed VM as completely different instructions. The v1.0.1 pin fixed
 *      the enum but not the off-by-one, and the symptom of both is identical:
 *      `ship()` never runs the program, so **nothing fails until a taker
 *      fills.** That is why the fill is a test and not a demo step.
 *
 * @dev The custody property that makes Aqua the right venue.
 *
 *      Aqua is a shared-liquidity *registry*: it records
 *      `balances[maker][app][strategyHash][token]` while the tokens themselves
 *      **stay in the maker's wallet**. The vault is the maker, so shipping a
 *      strategy moves no capital — exactly our locked Pattern 1 decision. A
 *      conventional AMM LP position would transfer tokens out to a pool and
 *      break that invariant.
 */
contract SwapVMProgramBuilder is DeployedAquaOpcodes {
    using ProgramBuilder for Program;

    /// @notice Thrown for a fee outside 0–10000 bps.
    error FeeOutOfRange(uint32 feeBps);

    uint32 internal constant _BPS = 10_000;

    /// @param aqua The Aqua registry, required by the inherited `Fee` module.
    ///        Only used for protocol-fee instructions, which we do not emit —
    ///        but the constructor demands it, so pass the real address.
    constructor(address aqua) DeployedAquaOpcodes(aqua) { }

    /**
     * @notice Build the SwapVM program bytecode for a constant-product position.
     * @dev Instruction order is load-bearing and mirrors 1inch's own
     *      `AquaStrategyBuilders.buildProgram`: fees must be applied *before*
     *      swap amounts are computed (`Fee.sol` reverts with
     *      `FeeShouldBeAppliedBeforeSwapAmountsComputation` otherwise). The
     *      trailing `Salt` makes two otherwise-identical strategies hash
     *      differently, so one vault can hold more than one.
     *
     *      Deliberately NOT included: any balances instruction. Under Aqua the
     *      virtual balances come from the `ship()` amounts themselves, so a
     *      `StaticBalances`/`DynamicBalances` opcode would be dead weight — and
     *      at v1.0.1 no balances instruction is wired into `AquaOpcodes` at all.
     *
     * @param feeBps    Maker fee on the input amount, in basis points.
     * @param salt      Uniqueness for the strategy hash. Supplied by the caller
     *                  so the result stays deterministic and reproducible.
     * @return program  Packed SwapVM bytecode.
     */
    function buildXYCProgram(uint32 feeBps, uint256 salt) public pure returns (bytes memory program) {
        if (feeBps > _BPS) revert FeeOutOfRange(feeBps);

        Program memory p = ProgramBuilder.init(_opcodes());

        bytes memory feeInstruction =
            feeBps > 0 ? p.build(Fee._flatFeeAmountInXD, FeeArgsBuilder.buildFlatFee(feeBps)) : bytes("");

        return bytes.concat(
            feeInstruction,
            p.build(XYCSwap._xycSwapXD),
            p.build(Controls._salt, abi.encodePacked(salt))
        );
    }

    /**
     * @notice Build the full strategy payload for `Aqua.ship()`, plus the hash
     *         that will identify it.
     * @dev `useAquaInsteadOfSignature` is set **true**. That is what makes the
     *      vault's Aqua balances stand in for an EIP-712 signature — essential
     *      here, because the vault is a contract and cannot sign anything. It
     *      is also the mode 1inch scores higher.
     *
     *      For Aqua orders `SwapVM.hash()` is `keccak256(abi.encode(order))` —
     *      pure, no chain state — so the hash comes back from the same call
     *      rather than needing a second lookup against the deployed SwapVM.
     *
     *      Note the token pair is **not** part of the strategy at v1.0.1: the
     *      deployed `swap()` takes `tokenIn`/`tokenOut` explicitly. One
     *      strategy therefore prices whatever pair a taker names against it,
     *      and the pair is fixed instead by the tokens passed to `ship()`.
     *
     * @param maker     The vault. Tokens never leave it.
     * @param feeBps    Maker fee in basis points.
     * @param salt      Strategy-hash uniqueness.
     * @return strategy      `abi.encode(order)` — pass verbatim to `Aqua.ship()`.
     * @return strategyHash  Identifies the position; needed later by `dock()`.
     */
    function buildStrategy(address maker, uint32 feeBps, uint256 salt)
        public
        pure
        returns (bytes memory strategy, bytes32 strategyHash)
    {
        ISwapVM.Order memory order = MakerTraitsLib.build(
            MakerTraitsLib.Args({
                maker: maker,
                receiver: address(0), // defaults to the maker — proceeds return to the vault
                shouldUnwrapWeth: false,
                useAquaInsteadOfSignature: true, // ← the Aqua mode. See the dev note above.
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
                program: buildXYCProgram(feeBps, salt)
            })
        );

        strategy = abi.encode(order);
        strategyHash = keccak256(strategy);
    }

    /**
     * @notice Sort two tokens, so an off-chain caller need not know the rule.
     * @dev Not required by the strategy at v1.0.1, but `ship()`'s `tokens` and
     *      `amounts` arrays must stay index-aligned, and a stable ordering makes
     *      a rebuilt position reproducible.
     */
    function sortTokens(address token0, address token1) public pure returns (address tokenA, address tokenB) {
        return token0 < token1 ? (token0, token1) : (token1, token0);
    }

    /**
     * @notice One `eth_call` for the whole job: sort the pair, build the
     *         strategy, and return the hash.
     * @dev Returns the sorted pair so the caller can line `ship()`'s `amounts`
     *      up with its `tokens` without re-deriving the order — which is how an
     *      amount ends up paired with the wrong token.
     */
    function buildStrategySorted(address maker, address token0, address token1, uint32 feeBps, uint256 salt)
        external
        pure
        returns (bytes memory strategy, bytes32 strategyHash, address tokenA, address tokenB)
    {
        (tokenA, tokenB) = sortTokens(token0, token1);
        (strategy, strategyHash) = buildStrategy(maker, feeBps, salt);
    }
}
