// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import { Test } from "forge-std/Test.sol";

import { ISwapVM } from "@1inch/swap-vm/src/interfaces/ISwapVM.sol";
import { MakerTraitsLib } from "@1inch/swap-vm/src/libs/MakerTraits.sol";

import { SwapVMProgramBuilder } from "../src/SwapVMProgramBuilder.sol";

/// @notice Asserts the two things that would silently produce a broken
///         position: the program's instruction encoding, and the Aqua mode bit.
contract SwapVMProgramBuilderTest is Test {
    SwapVMProgramBuilder internal builder;

    address internal constant AQUA = 0x499943E74FB0cE105688beeE8Ef2ABec5D936d31;
    address internal constant VAULT = 0x00000000000000000000000000000000000000A1;
    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant WETH = 0x4200000000000000000000000000000000000006;

    uint32 internal constant FEE_BPS = 30; // 0.30%
    uint256 internal constant SALT = 42;

    // ── Expected opcode numbers ───────────────────────────────────────────
    // POSITIONS in the instruction table of the SwapVM DEPLOYED ON BASE, taken
    // from that contract's own verified source. The builder derives them from
    // function pointers and never hardcodes them; this test hardcodes them
    // deliberately, so a change to the table fails HERE rather than at a live
    // fill.
    //
    // ⚠️ The comment that used to sit here said these were v1.0.1's positions
    // "which is what is deployed on Base". That was wrong, and the wrongness is
    // the whole of request #29: NO published swap-vm tag matches the deployed
    // contract. Its table carries an extra XYCConcentrate entry that v1.0.1
    // lacks, which pushes salt and the flat fee up by one. Compiled against the
    // package, salt resolved to 20 — and the deployed VM reads 20 as DECAY.
    //
    // Getting this wrong is never hypothetical and never loud. Compiled against
    // swap-vm `main` these were 0x50 / 0x02 / 0x70, from a banked hex enum that
    // replaced the positional scheme entirely. Every one of those variants
    // ships into Aqua without complaint, because `ship()` does not execute the
    // program. The first thing that runs it is a taker's fill.
    uint8 internal constant OP_XYC_SWAP = 17;
    uint8 internal constant OP_SALT = 21;
    uint8 internal constant OP_FLAT_FEE_IN = 22;

    /// @dev The deployed table's length. 28, not v1.0.1's 34 — confirmed
    ///      independently of the source by `SwapVMOpcodeTable.t.sol`, where
    ///      opcode 28 panics with array out-of-bounds on the live contract.
    uint8 internal constant DEPLOYED_TABLE_LENGTH = 28;

    function setUp() public {
        builder = new SwapVMProgramBuilder(AQUA);
    }

    // ── Program encoding ──────────────────────────────────────────────────

    function test_programEncodesFeeThenSwapThenSalt() public view {
        bytes memory program = builder.buildXYCProgram(FEE_BPS, SALT);

        bytes memory expected = abi.encodePacked(
            OP_FLAT_FEE_IN, uint8(4), FEE_BPS, // fee: uint32 arg
            OP_XYC_SWAP, uint8(0),             // swap: no args
            OP_SALT, uint8(32), SALT           // salt: uint256 arg
        );

        assertEq(program, expected, "program bytes drifted from the deployed opcode table");
    }

    /// @dev Fee must precede the swap: Fee.sol reverts with
    ///      FeeShouldBeAppliedBeforeSwapAmountsComputation otherwise.
    function test_feeInstructionPrecedesSwap() public view {
        bytes memory program = builder.buildXYCProgram(FEE_BPS, SALT);
        assertEq(uint8(program[0]), OP_FLAT_FEE_IN, "fee is not the first instruction");
        assertEq(uint8(program[6]), OP_XYC_SWAP, "swap does not follow the fee");
    }

    /// @dev Every opcode must be inside the deployed instruction table. A
    ///      number past its end is exactly the failure mode the `main`-branch
    ///      mismatch produced.
    ///
    ///      The bound used to be 35 — v1.0.1's length — which is loose enough
    ///      to admit every opcode the deployed VM can panic on. It passed
    ///      throughout #29 while the fee and salt were both wrong, so it is
    ///      pinned to the deployed length now.
    function test_everyOpcodeIsWithinTheDeployedInstructionTable() public view {
        bytes memory program = builder.buildXYCProgram(FEE_BPS, SALT);
        uint256 i = 0;
        while (i < program.length) {
            uint8 opcode = uint8(program[i]);
            uint8 argLen = uint8(program[i + 1]);
            assertLt(opcode, DEPLOYED_TABLE_LENGTH, "opcode past the end of the deployed instruction table");
            i += 2 + argLen;
        }
        assertEq(i, program.length, "program is not a clean opcode/length/args sequence");
    }

    function test_zeroFeeOmitsTheFeeInstruction() public view {
        bytes memory program = builder.buildXYCProgram(0, SALT);
        assertEq(uint8(program[0]), OP_XYC_SWAP, "zero fee should emit no fee instruction");
        assertEq(program.length, 2 + 2 + 32, "unexpected program length for a fee-free strategy");
    }

    function test_feeAboveBpsCeilingReverts() public {
        vm.expectRevert(abi.encodeWithSelector(SwapVMProgramBuilder.FeeOutOfRange.selector, uint32(10_001)));
        builder.buildXYCProgram(10_001, SALT);
    }

    function test_saltChangesTheProgram() public view {
        assertNotEq(
            keccak256(builder.buildXYCProgram(FEE_BPS, 1)),
            keccak256(builder.buildXYCProgram(FEE_BPS, 2)),
            "salt must make otherwise-identical strategies distinct"
        );
    }

    // ── Aqua mode ─────────────────────────────────────────────────────────

    /// @dev The single most important assertion in this lane. With this bit
    ///      clear, SwapVM demands an EIP-712 signature — which the vault, being
    ///      a contract with no key, can never produce. It is also the mode 1inch
    ///      scores higher.
    function test_useAquaInsteadOfSignatureIsSet() public view {
        (bytes memory strategy,) = builder.buildStrategy(VAULT, FEE_BPS, SALT);
        ISwapVM.Order memory order = abi.decode(strategy, (ISwapVM.Order));

        assertTrue(
            MakerTraitsLib.useAquaInsteadOfSignature(order.traits),
            "useAquaInsteadOfSignature must be true - the vault cannot sign"
        );
    }

    function test_strategyCarriesTheVaultAsMaker() public view {
        (bytes memory strategy,) = builder.buildStrategy(VAULT, FEE_BPS, SALT);
        ISwapVM.Order memory order = abi.decode(strategy, (ISwapVM.Order));

        // The vault is the maker, so tokens stay in the vault: Pattern 1 holds.
        assertEq(order.maker, VAULT, "the vault must be the Aqua maker");
    }

    /// @dev For Aqua orders SwapVM.hash() is keccak256(abi.encode(order)), so
    ///      the hash we return off-chain must equal what the chain computes.
    function test_strategyHashMatchesSwapVMDefinition() public view {
        (bytes memory strategy, bytes32 strategyHash) = builder.buildStrategy(VAULT, FEE_BPS, SALT);
        assertEq(strategyHash, keccak256(strategy), "hash must match SwapVM's Aqua-order definition");
    }

    /// @dev At v1.0.1 the order data is hooks + program only — no token prefix,
    ///      because the deployed swap() takes tokenIn/tokenOut explicitly. With
    ///      no hooks configured, the data IS the program.
    function test_programIsTheOrderData() public view {
        (bytes memory strategy,) = builder.buildStrategy(VAULT, FEE_BPS, SALT);
        ISwapVM.Order memory order = abi.decode(strategy, (ISwapVM.Order));
        bytes memory program = builder.buildXYCProgram(FEE_BPS, SALT);

        assertEq(order.data, program, "order data should be exactly the program when no hooks are set");
    }

    // ── Token ordering ────────────────────────────────────────────────────

    function test_sortTokensIsOrderIndependent() public view {
        (address a0, address b0) = builder.sortTokens(WETH, USDC);
        (address a1, address b1) = builder.sortTokens(USDC, WETH);
        assertEq(a0, a1);
        assertEq(b0, b1);
        assertEq(a0, WETH, "WETH (0x4200...) sorts BELOW USDC (0x8335...) on Base");
    }

    /// @dev The convenience entry point Python calls: one eth_call returns the
    ///      strategy, its hash, and the token order ship()'s amounts must line
    ///      up with.
    function test_buildStrategySortedAcceptsEitherOrder() public view {
        (bytes memory s0, bytes32 h0, address a0, address b0) =
            builder.buildStrategySorted(VAULT, USDC, WETH, FEE_BPS, SALT);
        (bytes memory s1, bytes32 h1,,) = builder.buildStrategySorted(VAULT, WETH, USDC, FEE_BPS, SALT);

        assertEq(h0, h1, "token argument order must not change the strategy");
        assertEq(keccak256(s0), keccak256(s1));
        assertEq(a0, WETH, "sorted tokenA is the lower address");
        assertEq(b0, USDC, "sorted tokenB is the higher address");
        assertGt(s0.length, 0, "strategy bytes must be non-empty");
    }

    function testFuzz_strategyIsAlwaysNonEmptyAndHashesConsistently(uint32 feeBps, uint256 salt) public view {
        feeBps = uint32(bound(feeBps, 0, 10_000));
        (bytes memory strategy, bytes32 strategyHash) = builder.buildStrategy(VAULT, feeBps, salt);
        assertGt(strategy.length, 0);
        assertEq(strategyHash, keccak256(strategy));
    }
}
