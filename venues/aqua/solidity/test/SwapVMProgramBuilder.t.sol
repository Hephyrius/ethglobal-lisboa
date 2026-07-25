// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import { Test } from "forge-std/Test.sol";

import { ISwapVM } from "@1inch/swap-vm/src/interfaces/ISwapVM.sol";
import { MakerTraits, MakerTraitsLib } from "@1inch/swap-vm/src/libs/MakerTraits.sol";
import { Opcode } from "@1inch/swap-vm/src/libs/OpcodeList.sol";

import { SwapVMProgramBuilder } from "../src/SwapVMProgramBuilder.sol";

/// @notice These assert the two things that would silently produce a broken
///         position: the program's instruction encoding, and the Aqua mode bit.
contract SwapVMProgramBuilderTest is Test {
    SwapVMProgramBuilder internal builder;

    // Real Base mainnet addresses. Note the ordering: WETH (0x4200…) sorts
    // BELOW USDC (0x8335…), because 0x42 < 0x83. It reads backwards if you
    // think in terms of "the quote asset comes first" — hence the explicit
    // TOKEN_A/TOKEN_B aliases, which are the order MakerTraitsLib requires.
    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant WETH = 0x4200000000000000000000000000000000000006;
    address internal constant TOKEN_A = WETH; // lower address
    address internal constant TOKEN_B = USDC; // higher address
    address internal constant VAULT = 0x00000000000000000000000000000000000000A1;

    uint32 internal constant FEE_BPS = 30; // 0.30%
    uint256 internal constant SALT = 42;

    function setUp() public {
        builder = new SwapVMProgramBuilder();
    }

    // ── Program encoding ──────────────────────────────────────────────────

    /// @dev SwapVM programs are `opcode ‖ argLength ‖ args` repeated. Pinning
    ///      the exact bytes is the whole point of building this in Solidity: if
    ///      1inch changes an opcode number, this fails here rather than at a
    ///      live `ship()`.
    function test_programEncodesFeeThenSwapThenSalt() public view {
        bytes memory program = builder.buildXYCProgram(FEE_BPS, SALT);

        bytes memory expected = abi.encodePacked(
            uint8(Opcode.FlatFeeAmountIn), uint8(4), FEE_BPS,   // fee: uint32 arg
            uint8(Opcode.XYCSwap), uint8(0),                    // swap: no args
            uint8(Opcode.Salt), uint8(32), SALT                 // salt: uint256 arg
        );

        assertEq(program, expected, "program bytes drifted from the opcode encoding");
    }

    /// @dev Fee must precede the swap: Fee.sol reverts with
    ///      FeeShouldBeAppliedBeforeSwapAmountsComputation otherwise.
    function test_feeInstructionPrecedesSwap() public view {
        bytes memory program = builder.buildXYCProgram(FEE_BPS, SALT);
        assertEq(uint8(program[0]), uint8(Opcode.FlatFeeAmountIn), "fee is not the first instruction");
        assertEq(uint8(program[6]), uint8(Opcode.XYCSwap), "swap does not follow the fee");
    }

    function test_zeroFeeOmitsTheFeeInstruction() public view {
        bytes memory program = builder.buildXYCProgram(0, SALT);
        assertEq(uint8(program[0]), uint8(Opcode.XYCSwap), "zero fee should emit no fee instruction");
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
        (bytes memory strategy,) = builder.buildStrategy(VAULT, TOKEN_A, TOKEN_B, FEE_BPS, SALT);
        ISwapVM.Order memory order = abi.decode(strategy, (ISwapVM.Order));

        assertTrue(
            MakerTraitsLib.useAquaInsteadOfSignature(order.traits),
            "useAquaInsteadOfSignature must be true - the vault cannot sign"
        );
    }

    function test_strategyCarriesTheVaultAsMaker() public view {
        (bytes memory strategy,) = builder.buildStrategy(VAULT, TOKEN_A, TOKEN_B, FEE_BPS, SALT);
        ISwapVM.Order memory order = abi.decode(strategy, (ISwapVM.Order));

        // The vault is the maker, so tokens stay in the vault: Pattern 1 holds.
        assertEq(order.maker, VAULT, "the vault must be the Aqua maker");
    }

    /// @dev For Aqua orders SwapVM.hash() is keccak256(abi.encode(order)), so
    ///      the hash we return off-chain must equal what the chain computes.
    function test_strategyHashMatchesSwapVMDefinition() public view {
        (bytes memory strategy, bytes32 strategyHash) = builder.buildStrategy(VAULT, TOKEN_A, TOKEN_B, FEE_BPS, SALT);
        assertEq(strategyHash, keccak256(strategy), "hash must match SwapVM's Aqua-order definition");
    }

    function test_programIsEmbeddedInTheOrderData() public view {
        (bytes memory strategy,) = builder.buildStrategy(VAULT, TOKEN_A, TOKEN_B, FEE_BPS, SALT);
        ISwapVM.Order memory order = abi.decode(strategy, (ISwapVM.Order));
        bytes memory program = builder.buildXYCProgram(FEE_BPS, SALT);

        // order.data is tokenA ‖ tokenB ‖ … ‖ program, so the program is the tail.
        assertGt(order.data.length, program.length, "order data should contain tokens plus the program");
        bytes memory tail = new bytes(program.length);
        for (uint256 i = 0; i < program.length; i++) {
            tail[i] = order.data[order.data.length - program.length + i];
        }
        assertEq(tail, program, "program must be embedded verbatim in the order data");
    }

    // ── Token ordering ────────────────────────────────────────────────────

    function test_unsortedTokensRevertRatherThanBuildABrokenStrategy() public {
        vm.expectRevert(abi.encodeWithSelector(SwapVMProgramBuilder.TokensNotSorted.selector, TOKEN_B, TOKEN_A));
        builder.buildStrategy(VAULT, TOKEN_B, TOKEN_A, FEE_BPS, SALT);
    }

    function test_sortTokensIsOrderIndependent() public view {
        (address a0, address b0) = builder.sortTokens(WETH, USDC);
        (address a1, address b1) = builder.sortTokens(USDC, WETH);
        assertEq(a0, a1);
        assertEq(b0, b1);
        assertEq(a0, WETH, "WETH (0x4200...) sorts BELOW USDC (0x8335...) on Base");
    }

    /// @dev The convenience entry point Python actually calls: one eth_call
    ///      returns the strategy, its hash, and the token order the ship()
    ///      amounts must line up with.
    function test_buildStrategySortedAcceptsEitherOrder() public view {
        (bytes memory s0, bytes32 h0, address a0, address b0) =
            builder.buildStrategySorted(VAULT, TOKEN_B, TOKEN_A, FEE_BPS, SALT);
        (bytes memory s1, bytes32 h1,,) = builder.buildStrategySorted(VAULT, TOKEN_A, TOKEN_B, FEE_BPS, SALT);

        assertEq(h0, h1, "token argument order must not change the strategy");
        assertEq(keccak256(s0), keccak256(s1));
        assertEq(a0, WETH, "sorted tokenA is the lower address");
        assertEq(b0, USDC, "sorted tokenB is the higher address");
        assertGt(s0.length, 0, "strategy bytes must be non-empty");
    }

    function testFuzz_strategyIsAlwaysNonEmptyAndHashesConsistently(uint32 feeBps, uint256 salt) public view {
        feeBps = uint32(bound(feeBps, 0, 10_000));
        (bytes memory strategy, bytes32 strategyHash) = builder.buildStrategy(VAULT, TOKEN_A, TOKEN_B, feeBps, salt);
        assertGt(strategy.length, 0);
        assertEq(strategyHash, keccak256(strategy));
    }
}
