// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import { ISwapVM } from "@1inch/swap-vm/src/interfaces/ISwapVM.sol";
import { MakerTraitsLib } from "@1inch/swap-vm/src/libs/MakerTraits.sol";
import { Opcode } from "@1inch/swap-vm/src/libs/OpcodeList.sol";
import { FeeArgsBuilder } from "@1inch/swap-vm/src/instructions/Fee.sol";
import { Program, ProgramBuilder } from "@1inch/swap-vm/test/utils/ProgramBuilder.sol";

/**
 * @title SwapVMProgramBuilder
 * @notice Compiles SwapVM strategy programs for an Aqua maker position. **Pure
 *         view contract — it holds nothing, moves nothing, and is never called
 *         by the vault.** It is deployed once and read with `eth_call`.
 *
 * @dev Why this contract exists at all.
 *
 *      SwapVM programs are packed bytecode: `opcode ‖ argLength ‖ args`, repeated.
 *      Reimplementing that encoding in Python would mean maintaining a second,
 *      unverified copy of 1inch's instruction format — and any drift produces a
 *      program that encodes cleanly and behaves wrongly with real money behind
 *      it. So the encoding happens **here**, in Solidity, against 1inch's own
 *      `ProgramBuilder`, `MakerTraitsLib` and `Opcode` definitions imported
 *      unmodified from their published packages. Python calls this and treats
 *      the result as opaque bytes.
 *
 *      This is also the seam that keeps Lane A and Lane D apart: the vault
 *      exposes one generic `execute(target, value, data)` and never learns what
 *      a SwapVM program is.
 *
 * @dev The custody property that makes Aqua the right venue here.
 *
 *      Aqua is a shared-liquidity *registry*: it records
 *      `balances[maker][app][strategyHash][token]` while the tokens themselves
 *      **stay in the maker's wallet**. The vault is the maker, so shipping a
 *      strategy moves no capital — which is exactly our locked Pattern 1
 *      decision (the vault is sole custodian and `totalAssets()` stays correct).
 *      A conventional AMM LP position would transfer tokens out to a pool and
 *      break that invariant.
 */
contract SwapVMProgramBuilder {
    using ProgramBuilder for Program;

    /// @notice Thrown when tokens are not in the ascending order MakerTraitsLib requires.
    error TokensNotSorted(address tokenA, address tokenB);

    /// @notice Thrown for a fee outside 0–10000 bps.
    error FeeOutOfRange(uint32 feeBps);

    uint32 internal constant _BPS = 10_000;

    /**
     * @notice Build the SwapVM program bytecode for a constant-product position.
     * @dev Instruction order is load-bearing and mirrors 1inch's own
     *      `AquaStrategyBuilders.buildProgram`: fees must be applied *before*
     *      swap amounts are computed, so the fee instruction precedes the swap.
     *      (`Fee.sol` reverts with `FeeShouldBeAppliedBeforeSwapAmountsComputation`
     *      otherwise.) The trailing `Salt` makes two otherwise-identical
     *      strategies hash differently, so a vault can hold more than one.
     *
     *      Deliberately NOT included: `DynamicBalances` (opcode 0x91). The
     *      master plan named it, but it is not wired into `AquaOpcodes` — under
     *      Aqua the virtual balances come from the `ship()` amounts themselves,
     *      so the instruction would be dead weight. See the build log.
     *
     * @param feeBps    Maker fee on the input amount, in basis points.
     * @param salt      Uniqueness for the strategy hash. Caller supplies it so
     *                  the result stays deterministic and reproducible.
     * @return program  Packed SwapVM bytecode.
     */
    function buildXYCProgram(uint32 feeBps, uint256 salt) public pure returns (bytes memory program) {
        if (feeBps > _BPS) revert FeeOutOfRange(feeBps);

        Program p;

        bytes memory feeInstruction =
            feeBps > 0 ? p.build(Opcode.FlatFeeAmountIn, FeeArgsBuilder.buildFlatFee(feeBps)) : bytes("");

        return bytes.concat(
            feeInstruction,
            p.build(Opcode.XYCSwap),
            p.build(Opcode.Salt, abi.encodePacked(salt))
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
     *      For Aqua orders `SwapVM.hash()` is defined as
     *      `keccak256(abi.encode(order))` — pure, no chain state — so the hash
     *      is returned from the same call rather than needing a second lookup
     *      against the deployed SwapVM.
     *
     * @param maker     The vault. Tokens never leave it.
     * @param tokenA    Lower-addressed token (MakerTraitsLib requires sorted).
     * @param tokenB    Higher-addressed token.
     * @param feeBps    Maker fee in basis points.
     * @param salt      Strategy-hash uniqueness.
     * @return strategy      `abi.encode(order)` — pass verbatim to `Aqua.ship()`.
     * @return strategyHash  Identifies the position; needed later by `dock()`.
     */
    function buildStrategy(address maker, address tokenA, address tokenB, uint32 feeBps, uint256 salt)
        public
        pure
        returns (bytes memory strategy, bytes32 strategyHash)
    {
        if (tokenA >= tokenB) revert TokensNotSorted(tokenA, tokenB);

        ISwapVM.Order memory order = MakerTraitsLib.build(
            MakerTraitsLib.Args({
                maker: maker,
                receiver: address(0), // defaults to the maker — proceeds return to the vault
                tokenA: tokenA,
                tokenB: tokenB,
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
     * @dev `MakerTraitsLib.build` requires `tokenA < tokenB` and reverts
     *      otherwise. Exposed as a helper so Python can order a pair without
     *      duplicating the invariant.
     */
    function sortTokens(address token0, address token1) public pure returns (address tokenA, address tokenB) {
        return token0 < token1 ? (token0, token1) : (token1, token0);
    }

    /**
     * @notice Convenience: sort, then build. One `eth_call` for the whole job.
     * @dev Returns the sorted order too, because `ship()`'s `tokens` and
     *      `amounts` arrays must be in the same order as the strategy's tokens.
     *      Returning them together removes the chance of the caller pairing an
     *      amount with the wrong token.
     */
    function buildStrategySorted(address maker, address token0, address token1, uint32 feeBps, uint256 salt)
        external
        pure
        returns (bytes memory strategy, bytes32 strategyHash, address tokenA, address tokenB)
    {
        (tokenA, tokenB) = sortTokens(token0, token1);
        (strategy, strategyHash) = buildStrategy(maker, tokenA, tokenB, feeBps, salt);
    }
}
