// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import { Context } from "@1inch/swap-vm/src/libs/VM.sol";
import { AquaOpcodes } from "@1inch/swap-vm/src/opcodes/AquaOpcodes.sol";
import { Controls } from "@1inch/swap-vm/src/instructions/Controls.sol";
import { Decay } from "@1inch/swap-vm/src/instructions/Decay.sol";
import { Fee } from "@1inch/swap-vm/src/instructions/Fee.sol";
import { XYCConcentrate } from "@1inch/swap-vm/src/instructions/XYCConcentrate.sol";
import { XYCSwap } from "@1inch/swap-vm/src/instructions/XYCSwap.sol";

/**
 * @title DeployedAquaOpcodes
 * @notice The instruction table of the SwapVM **actually deployed on Base** at
 *         `0x8fDD04Dbf6111437B44bbca99C28882434e0958f`, transcribed from that
 *         contract's own verified source.
 *
 * @dev This exists because request #29 was right and its cause was worse than
 *      suspected: **no published swap-vm tag matches what is deployed.** Only
 *      `0.0.1`–`0.0.6`, `v1.0.0` and `v1.0.1` exist, and the deployed table
 *      matches none of them. So there is no version to pin; the deployed
 *      contract is the only authority, and this file is its transcription.
 *
 * @dev What the difference is, exactly.
 *
 *      SwapVM opcodes are *positions* in `AquaOpcodes._opcodes()`. Against
 *      v1.0.1 the deployed table inserts one extra entry —
 *      `XYCConcentrate._xycConcentrateGrowLiquidityXD`, which does not exist in
 *      v1.0.1 at all — immediately after `XYCSwap`. Everything below it moves
 *      up by one:
 *
 *      | instruction            | v1.0.1 | **deployed** |
 *      |------------------------|--------|--------------|
 *      | `XYCSwap._xycSwapXD`   | 17     | **17**       |
 *      | `Decay._decayXD`       | 19     | **20**       |
 *      | `Controls._salt`       | 20     | **21**       |
 *      | `Fee._flatFeeAmountInXD` | 21   | **22**       |
 *
 *      So the swap was right and the fee and salt were each one too low. A
 *      program built against v1.0.1 therefore ships cleanly, hashes correctly,
 *      and asks the deployed VM to run **Decay where we meant Salt** — which is
 *      the `DecayShouldBeCalledBeforeSwapAmountsComputation` revert that kept
 *      `AquaTakerFillFork.t.sol` skipped for a wave.
 *
 * @dev Why the numbers still are not written down anywhere.
 *
 *      Nothing here hardcodes an opcode. This overrides the *table*; the
 *      builder still resolves each instruction by function pointer, so the
 *      numbers remain derived. What changed is which table they are derived
 *      from — 1inch's published one, or the one on chain. It has to be the
 *      latter.
 *
 *      `SwapVMOpcodeTable.t.sol` re-reads that table off the chain and asserts
 *      this transcription still matches, so a redeploy by 1inch fails a test
 *      here rather than silently mispricing a live position.
 *
 * @dev The `[29]` and the length rewrite are load-bearing — see the comment on
 *      the assembly block. Changing the array size changes every opcode.
 */
contract DeployedAquaOpcodes is AquaOpcodes {
    constructor(address aqua) AquaOpcodes(aqua) { }

    /**
     * @dev Transcribed from the deployed contract's verified `AquaOpcodes.sol`.
     *      Entry order is the whole meaning of this function; do not sort,
     *      dedupe or tidy it.
     */
    function _opcodes()
        internal
        pure
        virtual
        override
        returns (function(Context memory, bytes calldata) internal[] memory result)
    {
        function(Context memory, bytes calldata) internal[29] memory instructions = [
            // [0] is overwritten by the length below and is never reachable.
            _notInstruction,
            // Debug — reserved. Ten slots, exactly as deployed.
            _notInstruction,
            _notInstruction,
            _notInstruction,
            _notInstruction,
            _notInstruction,
            _notInstruction,
            _notInstruction,
            _notInstruction,
            _notInstruction,
            _notInstruction,
            // Controls — control flow.
            Controls._jump,
            Controls._jumpIfTokenIn,
            Controls._jumpIfTokenOut,
            Controls._deadline,
            Controls._onlyTakerTokenBalanceNonZero,
            Controls._onlyTakerTokenBalanceGte,
            Controls._onlyTakerTokenSupplyShareGte,
            // The swap. Opcode 17 once the length rewrite shifts everything.
            XYCSwap._xycSwapXD,
            // ⚠️ THE ENTRY THAT CAUSED #29. The deployed table has
            // `XYCConcentrate._xycConcentrateGrowLiquidityXD` here; v1.0.1 does
            // not have that function at all, so it cannot be named. The slot is
            // held open with `_notInstruction` because its *position* is what
            // matters — every opcode after it depends on this slot existing.
            // We never emit a concentrate instruction, so the placeholder is
            // never resolved; deleting it would silently decrement salt and fee.
            _notInstruction,
            XYCConcentrate._xycConcentrateGrowLiquidity2D,
            Decay._decayXD,
            Controls._salt,
            Fee._flatFeeAmountInXD,
            // The deployed tail is `_flatFeeAmountOutXD`, `_progressiveFeeInXD`,
            // `_progressiveFeeOutXD`, `_protocolFeeAmountOutXD` and
            // `_aquaProtocolFeeAmountOutXD`. v1.0.1 moved all five into a
            // separate `FeeExperimental` contract that `AquaOpcodes` does not
            // inherit, so they cannot be named from here either. They are held
            // open for the same reason as above — and because the table's
            // *length* is observable: opcode 28 panics with array
            // out-of-bounds on the deployed VM, which is how the size was
            // confirmed independently of the source.
            _notInstruction,
            _notInstruction,
            _notInstruction,
            _notInstruction,
            _notInstruction
        ];

        // Identical to 1inch's own trick, and it must stay identical. A fixed
        // memory array has no length prefix and a dynamic one does, so writing
        // the length over element [0] reinterprets the same memory as a dynamic
        // array starting at element [1]. Every opcode is therefore its position
        // here MINUS ONE.
        uint256 instructionsArrayLength = instructions.length - 1;
        assembly ("memory-safe") {
            result := instructions
            mstore(result, instructionsArrayLength)
        }
    }
}
