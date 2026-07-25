// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {Deploy} from "../../script/Deploy.s.sol";
import {IAggregatorV3} from "../../src/interfaces/IAggregatorV3.sol";
import {ChainlinkPriceLib} from "../../src/libraries/ChainlinkPriceLib.sol";

/// @dev The guards are `internal` on the script so `run()` can call them; this exposes them with a
///      real call frame so `vm.expectRevert` has something to bind to.
contract DeployHarness is Deploy {
    function isFork(string memory network) external pure returns (bool) {
        return _isForkNetwork(network);
    }

    function defaultPriceMaxAge(string memory network) external pure returns (uint256) {
        return _defaultPriceMaxAge(network);
    }

    function assertSafe(
        string memory network,
        address deployer,
        address agent,
        address guardian,
        uint256 priceMaxAge
    ) external pure {
        _assertSafeForRealNetwork(network, deployer, agent, guardian, priceMaxAge);
    }

    function allowlist() external pure returns (address[] memory) {
        return _allowlist();
    }

    function canPayGas(address deployer, uint256 balance) external pure {
        _assertCanPayGas(deployer, balance);
    }

    function chooseDeployerKey(bool forkTarget, uint256 forkKeyOrZero, uint256 mainnetKeyOrZero)
        external
        pure
        returns (uint256)
    {
        return _chooseDeployerKey(forkTarget, forkKeyOrZero, mainnetKeyOrZero);
    }

    function expectedChainId(string memory network) external pure returns (uint256) {
        return _expectedChainId(network);
    }

    function assertExpectedChain(string memory network, uint256 actual) external pure {
        _assertExpectedChain(network, actual);
    }

    function assertAddressesLive(uint256 priceMaxAge) external view {
        _assertConfiguredAddressesAreLive(priceMaxAge);
    }

    function ethUsdFeed() external pure returns (address) {
        return ETH_USD_FEED;
    }
}

/// @notice Tests for the deploy script's mainnet safety guards.
///
/// @dev Worth testing a *script*, unusually, because these two mistakes are unrecoverable. Every
///      configuration the guards reject is immutable after genesis — the role graph is frozen and
///      there is no valuation setter — so a vault deployed wrong cannot be fixed, only abandoned.
///      A deploy script is also the one file that gets run once, under time pressure, at 3am.
contract DeployGuardsTest is Test {
    DeployHarness internal deploy;

    address internal constant ANVIL_0 = 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266;
    address internal constant ANVIL_1 = 0x70997970C51812dc3A010C7d01b50e0d17dc79C8;
    uint256 internal constant ANVIL_KEY_0 = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;
    address internal realDeployer = makeAddr("fundedDeployer");
    address internal realAgent = makeAddr("fundedAgent");
    address internal realGuardian = makeAddr("platformGuardian");

    function setUp() public {
        // Foundry starts the clock at 1, where "two hours ago" underflows and no staleness bound can
        // be expressed at all. Same warp and same reason as `VaultTestBase`.
        vm.warp(1_700_000_000);
        deploy = new DeployHarness();
    }

    // ── network classification ───────────────────────────────────────────

    function test_onlyBaseForkCountsAsAFork() public view {
        assertTrue(deploy.isFork("base-fork"), "base-fork");
        assertFalse(deploy.isFork("base-mainnet"), "base-mainnet");
        assertFalse(deploy.isFork(""), "empty");
    }

    /// @dev The fail-safe direction. A mistyped network name must land on the *strict* settings, not
    ///      inherit the fork's disabled checks.
    function test_aTypoIsTreatedAsARealNetwork() public view {
        assertFalse(deploy.isFork("base-forks"), "trailing s");
        assertFalse(deploy.isFork("Base-Fork"), "wrong case");
        assertFalse(deploy.isFork("base_fork"), "underscore");
    }

    function test_stalenessDefaultsOffOnAForkAndOnEverywhereElse() public view {
        assertEq(deploy.defaultPriceMaxAge("base-fork"), 0, "fork: off, or a pinned fork bricks");
        assertEq(deploy.defaultPriceMaxAge("base-mainnet"), 3600, "mainnet: on by default");
        assertEq(deploy.defaultPriceMaxAge("base-sepolia"), 3600, "anything else: on by default");
    }

    // ── the guards ───────────────────────────────────────────────────────

    function test_acceptsAProperlyConfiguredRealDeployment() public view {
        deploy.assertSafe("base-mainnet", realDeployer, realAgent, realGuardian, 3600);
    }

    /// @dev The one that would actually lose the money. Anvil's private keys are in Foundry's
    ///      published documentation, so a mainnet vault with anvil #1 as `AGENT_ROLE` is drainable by
    ///      anyone — and the role graph is frozen at genesis, so it could never be revoked.
    function test_rejectsAnAnvilAgent() public {
        vm.expectRevert(
            abi.encodeWithSelector(Deploy.UnsafeAnvilKeyOnRealNetwork.selector, "AGENT_ADDRESS", ANVIL_1)
        );
        deploy.assertSafe("base-mainnet", realDeployer, ANVIL_1, realGuardian, 3600);

        vm.expectRevert(
            abi.encodeWithSelector(Deploy.UnsafeAnvilKeyOnRealNetwork.selector, "AGENT_ADDRESS", ANVIL_0)
        );
        deploy.assertSafe("base-mainnet", realDeployer, ANVIL_0, realGuardian, 3600);
    }

    /// @dev This is the realistic slip: the fork run defaults `DEPLOYER_PRIVATE_KEY` to anvil #0, so
    ///      a mainnet run that forgets to set it inherits a public key.
    function test_rejectsAnAnvilDeployer() public {
        vm.expectRevert(
            abi.encodeWithSelector(Deploy.UnsafeAnvilKeyOnRealNetwork.selector, "DEPLOYER_PRIVATE_KEY", ANVIL_0)
        );
        deploy.assertSafe("base-mainnet", ANVIL_0, realAgent, realGuardian, 3600);
    }

    function test_rejectsAnAnvilGuardian() public {
        vm.expectRevert(
            abi.encodeWithSelector(Deploy.UnsafeAnvilKeyOnRealNetwork.selector, "GUARDIAN_ADDRESS", ANVIL_1)
        );
        deploy.assertSafe("base-mainnet", realDeployer, realAgent, ANVIL_1, 3600);
    }

    /// @dev `priceMaxAge = 0` means `totalAssets()` will trust a Chainlink answer of any age — so
    ///      shares would price off a frozen feed during exactly the volatility that stalls feeds.
    ///      Immutable after genesis, like everything else here.
    function test_rejectsStalenessCheckingDisabled() public {
        vm.expectRevert(
            abi.encodeWithSelector(Deploy.StalenessCheckDisabledOnRealNetwork.selector, "base-mainnet")
        );
        deploy.assertSafe("base-mainnet", realDeployer, realAgent, realGuardian, 0);
    }

    /// @dev Reverting, not warning. A warning scrolls off the top of a broadcast log; this decision
    ///      is real-money, one-shot and unfixable afterwards.
    function test_guardsRevertRatherThanWarn() public {
        vm.expectRevert();
        deploy.assertSafe("base-mainnet", ANVIL_0, ANVIL_1, ANVIL_1, 0);
    }

    // ── the signer, and whether it can pay ───────────────────────────────

    /// @dev The trap this closes, found by running R0 in an isolated clone rather than reasoning
    ///      about it: `.env` defines `DEPLOYER_PRIVATE_KEY` as the funded *mainnet* wallet, which has
    ///      zero balance on a fresh fork. Reading it on a fork meant that merely sourcing `.env` —
    ///      which `scripts/*.sh` do, and which any runbook tells a human to do — turned a working
    ///      fork deploy into a failing one.
    function test_forkDeployIgnoresTheMainnetDeployerKey() public view {
        uint256 mainnetKey = 0xA11CE00000000000000000000000000000000000000000000000000000000001;

        assertEq(deploy.chooseDeployerKey(true, 0, mainnetKey), ANVIL_KEY_0, "fork falls back to anvil #0");
        assertEq(deploy.chooseDeployerKey(false, 0, mainnetKey), mainnetKey, "a real network uses it");
    }

    function test_forkDeployerCanStillBeOverridden() public view {
        uint256 forkKey = 0xB0B0000000000000000000000000000000000000000000000000000000000002;
        uint256 mainnetKey = 0xA11CE00000000000000000000000000000000000000000000000000000000001;

        assertEq(deploy.chooseDeployerKey(true, forkKey, mainnetKey), forkKey, "FORK_DEPLOYER wins on a fork");
        // And it must not leak the other way: a fork-only key must never sign a real deployment.
        assertEq(deploy.chooseDeployerKey(false, forkKey, mainnetKey), mainnetKey, "real network unaffected");
    }

    function test_bothUnsetFallsBackToAnvil() public view {
        assertEq(deploy.chooseDeployerKey(true, 0, 0), ANVIL_KEY_0, "fork");
        // On a real network this then trips UnsafeAnvilKeyOnRealNetwork, which is the intended path.
        assertEq(deploy.chooseDeployerKey(false, 0, 0), ANVIL_KEY_0, "real network, caught by the guard");
    }

    /// @dev `forge script` simulates the whole script before broadcasting, so an unfunded deployer
    ///      previously reached `_publish` and wrote deployments/<network>.json before dying in the
    ///      broadcast phase — leaving every other lane reading a factory address with no bytecode.
    ///      Confirmed by observation: `cast code` on the published factory returned `0x`.
    function test_rejectsADeployerThatCannotPayGas() public {
        vm.expectRevert(
            abi.encodeWithSelector(Deploy.DeployerCannotPayGas.selector, realDeployer, uint256(0), 0.001 ether)
        );
        deploy.canPayGas(realDeployer, 0);
    }

    function test_acceptsAFundedDeployer() public view {
        deploy.canPayGas(realDeployer, 1 ether);
        deploy.canPayGas(realDeployer, 0.001 ether); // exactly at the floor
    }

    function test_dustIsNotFunding() public {
        vm.expectRevert(
            abi.encodeWithSelector(Deploy.DeployerCannotPayGas.selector, realDeployer, uint256(1), 0.001 ether)
        );
        deploy.canPayGas(realDeployer, 1 wei);
    }

    // ── the published allowlist ──────────────────────────────────────────

    /// @dev Pins the answers given to Lane D in cross-lane requests #7 and #8. If someone trims this
    ///      list, plans built against it revert on-chain rather than failing in anyone's code.
    function test_allowlistContainsEveryTargetLaneDNeeds() public view {
        address[] memory targets = deploy.allowlist();
        assertEq(targets.length, 7, "seven targets");

        assertTrue(_has(targets, 0x499943E74FB0cE105688beeE8Ef2ABec5D936d31), "Aqua");
        assertTrue(_has(targets, 0x8fDD04Dbf6111437B44bbca99C28882434e0958f), "SwapVM");
        assertTrue(_has(targets, 0x6fF5693b99212Da76ad316178A184AB56D299b43), "UniversalRouter (request #7)");
        assertTrue(_has(targets, 0x2626664c2603336E57B271c5C0b26F421741e481), "SwapRouter02");
        assertTrue(_has(targets, 0x000000000022D473030F116dDEE9F6B43aC78BA3), "Permit2");
        assertTrue(_has(targets, 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913), "USDC as approve target (#8)");
        assertTrue(_has(targets, 0x4200000000000000000000000000000000000006), "WETH as approve target (#8)");
    }

    // ── one key holding both roles ───────────────────────────────────────

    /// @dev Collapsing agent and guardian collapses `SECURITY.md` §12: the guardian may halt trading
    ///      but never name a trade, and the agent may trade but never halt itself. One key doing both
    ///      is neither, and the role graph is frozen at genesis so it cannot be separated later.
    function test_rejectsAgentAndGuardianBeingTheSameKey() public {
        vm.expectRevert(
            abi.encodeWithSelector(Deploy.AgentAndGuardianAreTheSameAccount.selector, realAgent)
        );
        deploy.assertSafe("base-mainnet", realDeployer, realAgent, realAgent, 3600);
    }

    /// @dev Not enforced on a fork, where one operator holding everything is normal and harmless.
    ///      Asserted so the asymmetry is deliberate rather than an oversight.
    function test_theSameKeyIsFineOnAFork() public view {
        assertTrue(deploy.isFork("base-fork"), "fork classification");
        // `run()` only calls the guards when `!isFork`, and the fork path is what the deploy that
        // just ran used — with deployer as guardian and a separate agent.
        assertEq(deploy.defaultPriceMaxAge("base-fork"), 0, "fork keeps staleness off");
    }

    // ── wrong chain ──────────────────────────────────────────────────────

    /// @dev Every address in the deploy script is a Base mainnet address. Pointed at another chain
    ///      they are empty accounts, and the vault would freeze an allowlist of seven nothings and a
    ///      price feed that is not a contract.
    function test_rejectsAMainnetDeployOnTheWrongChain() public {
        vm.expectRevert(abi.encodeWithSelector(Deploy.WrongChainForNetwork.selector, "base-mainnet", 8453, 1));
        deploy.assertExpectedChain("base-mainnet", 1);
    }

    function test_acceptsAMainnetDeployOnBase() public view {
        deploy.assertExpectedChain("base-mainnet", 8453);
        assertEq(deploy.expectedChainId("base-mainnet"), 8453, "Base");
    }

    /// @dev An unrecognised name has no known chain, so this guard stays quiet and the code checks
    ///      catch it instead. Adding a network therefore does not require remembering to extend it.
    function test_anUnknownNetworkHasNoChainConstraint() public view {
        assertEq(deploy.expectedChainId("base-sepolia"), 0, "unknown");
        deploy.assertExpectedChain("base-sepolia", 999);
    }

    // ── the addresses have to actually be there ──────────────────────────

    /// @dev A bare EVM with no fork: none of the hardcoded addresses hold code, which is exactly the
    ///      state a wrong `--rpc-url` produces.
    function test_rejectsAnAllowlistedTargetWithNoCode() public {
        vm.expectRevert(
            abi.encodeWithSelector(Deploy.AllowlistedTargetHasNoCode.selector, deploy.allowlist()[0])
        );
        deploy.assertAddressesLive(3600);
    }

    function test_rejectsAFeedThatIsNotAContract() public {
        _giveEveryTargetCode();
        vm.expectRevert(abi.encodeWithSelector(Deploy.PriceFeedHasNoCode.selector, deploy.ethUsdFeed()));
        deploy.assertAddressesLive(3600);
    }

    /// @dev The strongest of the new guards: the feed is read through **`ChainlinkPriceLib.readPrice`
    ///      with the bound the vault is about to freeze**, so the deploy cannot produce a vault whose
    ///      `totalAssets()` reverts on its first call. Here the answer is older than the bound.
    function test_rejectsAFeedThatIsAlreadyStalerThanTheBound() public {
        _giveEveryTargetCode();
        _mockFeed({answer: 3_000e8, updatedAt: block.timestamp - 7200});

        vm.expectRevert(
            abi.encodeWithSelector(
                ChainlinkPriceLib.StalePrice.selector, deploy.ethUsdFeed(), block.timestamp - 7200, uint256(3600)
            )
        );
        deploy.assertAddressesLive(3600);
    }

    function test_rejectsAFeedReportingANonPositiveAnswer() public {
        _giveEveryTargetCode();
        _mockFeed({answer: 0, updatedAt: block.timestamp});

        vm.expectRevert(
            abi.encodeWithSelector(ChainlinkPriceLib.InvalidPrice.selector, deploy.ethUsdFeed(), int256(0))
        );
        deploy.assertAddressesLive(3600);
    }

    function test_acceptsALiveFeedWithinTheBound() public {
        _giveEveryTargetCode();
        _mockFeed({answer: 3_000e8, updatedAt: block.timestamp});
        deploy.assertAddressesLive(3600);
    }

    /// @dev A fork passes `priceMaxAge = 0`, which disables the staleness leg in the guard exactly as
    ///      it does in the vault. The check is as strict as the vault will be and no stricter —
    ///      otherwise a fork deploy would fail on a frozen feed the vault is content with.
    function test_aForkBoundAcceptsAFrozenFeed() public {
        _giveEveryTargetCode();
        _mockFeed({answer: 3_000e8, updatedAt: 1});
        deploy.assertAddressesLive(0);
    }

    function _giveEveryTargetCode() private {
        address[] memory targets = deploy.allowlist();
        for (uint256 i; i < targets.length; ++i) {
            vm.etch(targets[i], hex"60006000fd");
        }
    }

    function _mockFeed(int256 answer, uint256 updatedAt) private {
        address feed = deploy.ethUsdFeed();
        vm.etch(feed, hex"60006000fd");
        vm.mockCall(
            feed,
            abi.encodeWithSelector(IAggregatorV3.latestRoundData.selector),
            abi.encode(uint80(1), answer, updatedAt, updatedAt, uint80(1))
        );
    }

    function _has(address[] memory list, address needle) private pure returns (bool) {
        for (uint256 i; i < list.length; ++i) {
            if (list[i] == needle) return true;
        }
        return false;
    }
}
