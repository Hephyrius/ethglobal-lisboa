// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import { Test } from "forge-std/Test.sol";
import { IERC20 } from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import { IAqua } from "@1inch/aqua/src/interfaces/IAqua.sol";

import { SwapVMProgramBuilder } from "../src/SwapVMProgramBuilder.sol";

/**
 * @notice Minimal stand-in for Lane A's `CuratedVault`, implementing only the
 *         documented agent seam from `contracts/README.md`:
 *
 *             function execute(address target, uint256 value, bytes calldata data)
 *             function executeBatch(Call[] calldata calls)
 *             struct Call { address target; uint256 value; bytes data; }
 *
 * @dev This is **not** a copy of Lane A's vault and does not test it — Lane D
 *      never reads `contracts/`. It is a relay with the same shape, built from
 *      the published interface, so this lane can verify the one property its
 *      own tests could not otherwise reach: that an `ExecutionPlan` still works
 *      when the caller is a **contract** rather than an externally-owned
 *      account. Lane A's real vault is tested by Lane A.
 */
contract MockAgentVault {
    struct Call {
        address target;
        uint256 value;
        bytes data;
    }

    error TargetNotAllowed(address target);

    mapping(address => bool) public allowedTargets;

    constructor(address[] memory targets) {
        for (uint256 i = 0; i < targets.length; i++) {
            allowedTargets[targets[i]] = true;
        }
    }

    function execute(address target, uint256 value, bytes calldata data)
        public
        returns (bytes memory)
    {
        if (!allowedTargets[target]) revert TargetNotAllowed(target);
        (bool ok, bytes memory ret) = target.call{ value: value }(data);
        if (!ok) {
            assembly {
                revert(add(ret, 0x20), mload(ret))
            }
        }
        return ret;
    }

    function executeBatch(Call[] calldata calls) external returns (bytes[] memory results) {
        results = new bytes[](calls.length);
        for (uint256 i = 0; i < calls.length; i++) {
            results[i] = execute(calls[i].target, calls[i].value, calls[i].data);
        }
    }
}

/**
 * @title VaultRelayFork
 * @notice Runs a complete Aqua `ExecutionPlan` through a vault-shaped relay
 *         against the **real deployed Aqua** on a Base fork.
 *
 * @dev Why this is not redundant with `AquaShipFork.t.sol`. That test pranks a
 *      plain address, so `msg.sender` at Aqua is an EOA. In production the
 *      maker is the **vault** — a contract with no private key — and the calls
 *      arrive relayed through `execute()`. That difference is the entire reason
 *      `useAquaInsteadOfSignature = true` exists: a signature-based order would
 *      require the maker to sign, which a contract cannot do. This proves the
 *      Aqua-balances path actually works for a contract maker end to end,
 *      rather than assuming it does.
 *
 *      It also exercises the plan the way Lane B submits it — as one atomic
 *      `executeBatch`, steps in the order this lane emits them.
 */
contract VaultRelayForkTest is Test {
    IAqua internal constant AQUA = IAqua(0x499943E74FB0cE105688beeE8Ef2ABec5D936d31);
    address internal constant SWAPVM = 0x8fDD04Dbf6111437B44bbca99C28882434e0958f;

    IERC20 internal constant USDC = IERC20(0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913);
    IERC20 internal constant WETH = IERC20(0x4200000000000000000000000000000000000006);

    // WETH sorts below USDC on Base, so it is tokenA.
    address internal constant TOKEN_A = address(WETH);
    address internal constant TOKEN_B = address(USDC);

    uint256 internal constant WETH_AMOUNT = 3 ether;
    uint256 internal constant USDC_AMOUNT = 10_000e6;
    uint32 internal constant FEE_BPS = 30;
    uint256 internal constant SALT = 0xC0FFEE;

    SwapVMProgramBuilder internal builder;
    MockAgentVault internal vault;

    function setUp() public {
        string memory rpc = vm.envOr("BASE_RPC_URL", string("https://mainnet.base.org"));
        try vm.createSelectFork(rpc) {
            // forked
        } catch {
            vm.skip(true);
        }

        builder = new SwapVMProgramBuilder(address(AQUA));

        // Exactly the allowlist Lane A publishes in deployments/base-fork.json.
        address[] memory targets = new address[](3);
        targets[0] = address(AQUA);
        targets[1] = TOKEN_A;
        targets[2] = TOKEN_B;
        vault = new MockAgentVault(targets);

        deal(address(WETH), address(vault), WETH_AMOUNT);
        deal(address(USDC), address(vault), USDC_AMOUNT);
    }

    /// @dev The three steps `AquaVenue.plan()` emits, in the order it emits
    ///      them: approve tokenA, approve tokenB, ship.
    function _planSteps()
        internal
        view
        returns (MockAgentVault.Call[] memory calls, bytes32 expectedHash)
    {
        bytes memory strategy;
        (strategy, expectedHash,,) =
            builder.buildStrategySorted(address(vault), TOKEN_A, TOKEN_B, FEE_BPS, SALT);

        address[] memory tokens = new address[](2);
        tokens[0] = TOKEN_A;
        tokens[1] = TOKEN_B;
        uint256[] memory amounts = new uint256[](2);
        amounts[0] = WETH_AMOUNT;
        amounts[1] = USDC_AMOUNT;

        calls = new MockAgentVault.Call[](3);
        calls[0] = MockAgentVault.Call({
            target: TOKEN_A,
            value: 0,
            data: abi.encodeCall(IERC20.approve, (address(AQUA), WETH_AMOUNT))
        });
        calls[1] = MockAgentVault.Call({
            target: TOKEN_B,
            value: 0,
            data: abi.encodeCall(IERC20.approve, (address(AQUA), USDC_AMOUNT))
        });
        calls[2] = MockAgentVault.Call({
            target: address(AQUA),
            value: 0,
            data: abi.encodeCall(IAqua.ship, (SWAPVM, strategy, tokens, amounts))
        });
    }

    /// @dev The headline: a contract maker can open an Aqua position. If
    ///      `useAquaInsteadOfSignature` were false this would be unreachable,
    ///      because the vault cannot produce a signature.
    function test_contractMakerCanShipThroughExecuteBatch() public {
        (MockAgentVault.Call[] memory calls, bytes32 expectedHash) = _planSteps();

        bytes[] memory results = vault.executeBatch(calls);

        bytes32 strategyHash = abi.decode(results[2], (bytes32));
        assertEq(strategyHash, expectedHash, "on-chain hash differs from the one we computed");

        (uint256 balanceA, uint256 balanceB) =
            AQUA.safeBalances(address(vault), SWAPVM, strategyHash, TOKEN_A, TOKEN_B);
        assertEq(balanceA, WETH_AMOUNT, "WETH virtual balance wrong");
        assertEq(balanceB, USDC_AMOUNT, "USDC virtual balance wrong");
    }

    /// @dev Pattern 1 again, now through the relay: `totalAssets()` reads plain
    ///      `balanceOf`, so if shipping moved anything the vault's accounting
    ///      would be wrong the moment a position opened.
    function test_shippingThroughTheVaultStillMovesNoTokens() public {
        (MockAgentVault.Call[] memory calls,) = _planSteps();

        uint256 wethBefore = WETH.balanceOf(address(vault));
        uint256 usdcBefore = USDC.balanceOf(address(vault));

        vault.executeBatch(calls);

        assertEq(WETH.balanceOf(address(vault)), wethBefore, "WETH left the vault");
        assertEq(USDC.balanceOf(address(vault)), usdcBefore, "USDC left the vault");
    }

    /// @dev The maker recorded inside the strategy must be the address that
    ///      calls `ship()`. If a plan were built with the agent's address as
    ///      maker instead of the vault's, this is where it would surface —
    ///      Aqua would credit balances to an address holding no tokens.
    function test_makerIsTheVaultNotTheCaller() public {
        (MockAgentVault.Call[] memory calls, bytes32 expectedHash) = _planSteps();

        // Submitted by an arbitrary EOA standing in for the agent's key.
        address agent = makeAddr("agent-key");
        vm.prank(agent);
        vault.executeBatch(calls);

        (uint256 balanceA,) =
            AQUA.safeBalances(address(vault), SWAPVM, expectedHash, TOKEN_A, TOKEN_B);
        assertEq(balanceA, WETH_AMOUNT, "balances should be credited to the vault");

        // Nothing is credited to the agent — it authorises, it does not custody.
        vm.expectRevert();
        AQUA.safeBalances(agent, SWAPVM, expectedHash, TOKEN_A, TOKEN_B);
    }

    /// @dev **A trap, found by this test failing.** `ship()` does NOT revert
    ///      without approvals — it succeeds, records full virtual balances, and
    ///      reports a healthy position.
    ///
    ///      That follows from Aqua's design: shipping moves nothing, so there
    ///      is nothing to approve *yet*. The allowance is consumed later, when
    ///      a taker fills and Aqua `pull()`s from the maker's wallet.
    ///
    ///      The consequence is worse than a revert, which is why it is pinned
    ///      here. A plan that omitted the approvals would look completely
    ///      successful — non-zero balances, a valid strategy hash, no error
    ///      anywhere — and then quietly fail to ever be filled. The position
    ///      would earn nothing and nobody would be told why. So the approval
    ///      steps in `AquaVenue.plan()` are not belt-and-braces ordering; they
    ///      are the only thing that makes the position real, and their absence
    ///      is undetectable at execution time.
    function test_shipWithoutApprovalsSucceedsButLeavesThePositionUnfillable() public {
        (MockAgentVault.Call[] memory calls, bytes32 expectedHash) = _planSteps();

        MockAgentVault.Call[] memory shipOnly = new MockAgentVault.Call[](1);
        shipOnly[0] = calls[2];

        bytes[] memory results = vault.executeBatch(shipOnly);
        assertEq(
            abi.decode(results[0], (bytes32)), expectedHash, "ship should still succeed"
        );

        // Looks entirely healthy...
        (uint256 balanceA, uint256 balanceB) =
            AQUA.safeBalances(address(vault), SWAPVM, expectedHash, TOKEN_A, TOKEN_B);
        assertEq(balanceA, WETH_AMOUNT);
        assertEq(balanceB, USDC_AMOUNT);

        // ...but Aqua cannot move a thing when a taker arrives.
        assertEq(WETH.allowance(address(vault), address(AQUA)), 0, "no allowance to pull");
        assertEq(USDC.allowance(address(vault), address(AQUA)), 0, "no allowance to pull");
    }

    /// @dev The full plan, by contrast, leaves exactly the allowances a fill
    ///      needs — which is the property that actually matters.
    function test_fullPlanLeavesTheAllowancesAFillRequires() public {
        (MockAgentVault.Call[] memory calls,) = _planSteps();
        vault.executeBatch(calls);

        assertEq(WETH.allowance(address(vault), address(AQUA)), WETH_AMOUNT);
        assertEq(USDC.allowance(address(vault), address(AQUA)), USDC_AMOUNT);
    }

    /// @dev A non-allowlisted target is refused by the vault, mirroring the
    ///      check `assert_targets_allowlisted` performs off-chain. Both layers
    ///      exist so the failure is caught early *and* enforced late.
    function test_nonAllowlistedTargetIsRefused() public {
        MockAgentVault.Call[] memory calls = new MockAgentVault.Call[](1);
        calls[0] = MockAgentVault.Call({
            target: SWAPVM, // deliberately not in this vault's allowlist
            value: 0,
            data: ""
        });

        vm.expectRevert(
            abi.encodeWithSelector(MockAgentVault.TargetNotAllowed.selector, SWAPVM)
        );
        vault.executeBatch(calls);
    }

    /// @dev Closing the position through the relay, capital-neutral as ever.
    function test_dockThroughTheVaultClearsBalances() public {
        (MockAgentVault.Call[] memory calls, bytes32 expectedHash) = _planSteps();
        vault.executeBatch(calls);

        address[] memory tokens = new address[](2);
        tokens[0] = TOKEN_A;
        tokens[1] = TOKEN_B;

        uint256 wethBefore = WETH.balanceOf(address(vault));
        vault.execute(
            address(AQUA), 0, abi.encodeCall(IAqua.dock, (SWAPVM, expectedHash, tokens))
        );

        assertEq(WETH.balanceOf(address(vault)), wethBefore, "dock moved tokens");
        vm.expectRevert();
        AQUA.safeBalances(address(vault), SWAPVM, expectedHash, TOKEN_A, TOKEN_B);
    }
}
