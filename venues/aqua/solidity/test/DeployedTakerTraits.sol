// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/**
 * @title DeployedTakerTraits
 * @notice Encodes taker traits in the wire format the **deployed** SwapVM on
 *         Base actually parses.
 *
 * @dev Test support only, and deliberately so. Our vault is always the *maker*
 *      — it posts a curve and waits. Taker traits are built by whoever fills,
 *      using 1inch's own tooling. Nothing in `venues/` production code encodes
 *      this, and nothing should.
 *
 * @dev Why we cannot use `TakerTraitsLib` from the npm package.
 *
 *      v1.0.1 added a `Deadline` slice to `TakerDataSlices`, taking the packed
 *      slice-index word from **nine** 16-bit fields to **ten** — `uint144` to
 *      `uint160`. The flag bits are identical in both versions, but they sit
 *      *after* that word, so two extra bytes ahead of them shifts the entire
 *      structure.
 *
 *      The result is not a revert. The deployed VM reads a valid-looking traits
 *      word with the wrong bits in it: `isExactIn` comes back **false**, the
 *      swap runs as exact-output, and the quote is arithmetically correct for a
 *      trade nobody asked for. Ours returned `amountIn = 4` — precisely
 *      `ceil(1e9 · 1e10 / (3e18 − 1e9))`, the exact-out answer — where the
 *      exact-in answer was 1e9.
 *
 *      **That number is why this file exists rather than a `vm.skip`.** A
 *      revert would have been obvious. A plausible quote computed under the
 *      wrong flag is the same class of failure as the opcode off-by-one it sat
 *      behind: correct arithmetic, wrong question, silent.
 *
 * @dev Layout, from the deployed contract's own verified source
 *      (`0x8fDD04Dbf6111437B44bbca99C28882434e0958f`, `src/libs/TakerTraits.sol`):
 *
 *      ```
 *      uint144 slicesIndexes   ‖ uint16 flags ‖ threshold ‖ to ‖ hooks… ‖ signature
 *      ```
 *
 *      Every slice index is a cumulative byte offset into the trailing data. We
 *      only ever need the all-empty case — no threshold, no custom recipient,
 *      no hooks, no callbacks, no signature (Aqua mode replaces it) — so every
 *      index is zero and the whole encoding is 20 bytes.
 */
library DeployedTakerTraits {
    uint16 internal constant IS_EXACT_IN = 0x0001;
    uint16 internal constant SHOULD_UNWRAP = 0x0002;
    uint16 internal constant HAS_PRE_TRANSFER_IN_CALLBACK = 0x0004;
    uint16 internal constant HAS_PRE_TRANSFER_OUT_CALLBACK = 0x0008;
    uint16 internal constant IS_STRICT_THRESHOLD = 0x0010;
    uint16 internal constant IS_FIRST_TRANSFER_FROM_TAKER = 0x0020;
    uint16 internal constant USE_TRANSFER_FROM_AND_AQUA_PUSH = 0x0040;

    /**
     * @notice A plain taker fill against an Aqua maker position.
     * @dev `isFirstTransferFromTaker` and `useTransferFromAndAquaPush` together
     *      are what let a taker with no Aqua balance of its own trade against
     *      one: SwapVM `transferFrom`s the taker's input and `push`es it into
     *      the maker's Aqua balance, then `pull`s the output from the maker's
     *      wallet. Both transfers are real ERC-20 movements.
     * @param isExactIn Exact-input when true. Verify this landed by checking
     *        the returned `amountIn`, not by trusting the flag — see the note
     *        above on how quietly it fails.
     */
    function simpleFill(bool isExactIn) internal pure returns (bytes memory) {
        uint16 flags = IS_FIRST_TRANSFER_FROM_TAKER | USE_TRANSFER_FROM_AND_AQUA_PUSH;
        if (isExactIn) flags |= IS_EXACT_IN;
        // uint144(0): all nine slice indexes are zero because every optional
        // field is empty. Its *width* is the whole point of this file.
        return abi.encodePacked(uint144(0), flags);
    }
}
