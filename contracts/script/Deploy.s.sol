// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";

import {CuratedVault} from "../src/CuratedVault.sol";
import {VaultFactory} from "../src/VaultFactory.sol";
import {ICuratedVault} from "../src/interfaces/ICuratedVault.sol";
import {IVaultFactory} from "../src/interfaces/IVaultFactory.sol";

/// @title Deploy — factory, implementation and one demo vault, then publish the addresses.
///
/// @notice One script for both targets. `DEPLOY_NETWORK=base-fork` (the default) writes
///         `deployments/base-fork.json`; `base-mainnet` writes `deployments/base-mainnet.json`.
///         Everything else is environment-driven, so there is no second copy of this file to drift.
///
/// @dev Writing the deployments file is part of the deploy, not a follow-up step. Every other lane
///      reads addresses from that file rather than hardcoding them, so a deploy that does not
///      publish is a deploy that silently breaks four other lanes.
///
///      Usage (inside `wsl -d Ubuntu-24.04`, with `scripts/anvil-fork.sh` already running):
///        forge script script/Deploy.s.sol --rpc-url http://127.0.0.1:8540 --broadcast
contract Deploy is Script {
    // Live Base mainnet addresses. Every one of these was confirmed against forked state before
    // being written down — `cast code` returns bytecode and the feed answers `description()`.
    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant WETH = 0x4200000000000000000000000000000000000006;
    address internal constant AQUA = 0x499943E74FB0cE105688beeE8Ef2ABec5D936d31;
    address internal constant SWAPVM = 0x8fDD04Dbf6111437B44bbca99C28882434e0958f;
    address internal constant PERMIT2 = 0x000000000022D473030F116dDEE9F6B43aC78BA3;

    /// @dev Confirmed by Lane D against a live Trading API `/swap` response, which returns this as
    ///      the transaction `to`. Cross-lane request #7.
    address internal constant UNIVERSAL_ROUTER = 0x6fF5693b99212Da76ad316178A184AB56D299b43;
    /// @dev The router in the golden fixture. Kept on the list because an extra allowlisted venue
    ///      costs nothing and a missing one reverts every plan built against it.
    address internal constant SWAP_ROUTER_02 = 0x2626664c2603336E57B271c5C0b26F421741e481;

    /// @dev Chainlink ETH/USD on Base. Verified live: `description()` returns "ETH / USD",
    ///      `decimals()` returns 8.
    address internal constant ETH_USD_FEED = 0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70;

    /// @dev Anvil's first two accounts. **Their private keys are published in Foundry's own docs**,
    ///      so anyone can sign as them. Fine on a throwaway fork, catastrophic anywhere real — which
    ///      is what `_assertSafeForRealNetwork` exists to prevent.
    uint256 internal constant ANVIL_ACCOUNT_0 = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;
    address internal constant ANVIL_ADDRESS_0 = 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266;
    address internal constant ANVIL_ADDRESS_1 = 0x70997970C51812dc3A010C7d01b50e0d17dc79C8;

    /// @dev Base's ETH/USD feed has a 1200s heartbeat; 3600s absorbs a missed round without
    ///      bricking accounting. Applied automatically to every network except a fork.
    uint256 internal constant LIVE_PRICE_MAX_AGE = 3600;

    /// @dev The only network name that gets fork defaults. Anything unrecognised is treated as real,
    ///      so a typo fails safe rather than shipping a vault with its safety checks off.
    string internal constant FORK_NETWORK = "base-fork";

    /// @dev A sanity floor, not a precise estimate. The deploy costs ~6.9M gas, which on Base is
    ///      well under 0.0001 ETH — this is set far above that so it only ever catches an
    ///      unfunded account, never a merely frugal one.
    uint256 internal constant MIN_DEPLOYER_BALANCE = 0.001 ether;

    error UnsafeAnvilKeyOnRealNetwork(string what, address account);
    error StalenessCheckDisabledOnRealNetwork(string network);
    error DeployerCannotPayGas(address deployer, uint256 balance, uint256 minimum);

    function run() external {
        string memory network = vm.envOr("DEPLOY_NETWORK", string("base-fork"));
        bool isFork = _isForkNetwork(network);

        uint256 deployerKey = _resolveDeployerKey(isFork);
        address deployer = vm.addr(deployerKey);

        address agent = vm.envOr("AGENT_ADDRESS", ANVIL_ADDRESS_1);
        address guardian = vm.envOr("GUARDIAN_ADDRESS", deployer);

        // 0 disables the Chainlink staleness check — required on a pinned fork, where the forked
        // feed's `updatedAt` is frozen while block.timestamp keeps advancing. The default is now
        // network-derived rather than a flat 0, because "remember to set PRICE_MAX_AGE" is exactly
        // the step that gets forgotten at 3am on the mainnet run. Explicit env always wins.
        uint256 priceMaxAge = vm.envOr("PRICE_MAX_AGE", _defaultPriceMaxAge(network));

        bytes32 mandateHash = vm.envOr("MANDATE_HASH", keccak256("demo-mandate-v1"));

        if (!isFork) _assertSafeForRealNetwork(network, deployer, agent, guardian, priceMaxAge);

        // Before anything is broadcast *or published*. `forge script` runs the whole script in
        // simulation first, so without this an unfunded deployer gets as far as writing
        // deployments/<network>.json and only then dies in the broadcast phase — leaving four lanes
        // reading addresses that have no bytecode. Observed, not hypothesised.
        _assertCanPayGas(deployer, deployer.balance);

        vm.startBroadcast(deployerKey);

        VaultFactory factory =
            new VaultFactory(deployer, _allowlist(), _valuations(), priceMaxAge);

        address vault = factory.createVault(
            IVaultFactory.CreateParams({
                asset: USDC,
                name: "Curated USDC Vault",
                symbol: "cUSDC",
                agent: agent,
                guardian: guardian,
                mandateHash: mandateHash,
                // The genesis vault has no human behind it — it is deployed by the script, not
                // requested by anyone. Recording the broadcasting key is the truthful answer, and
                // address(0) gets there without hardcoding it.
                deployer: address(0)
            })
        );

        vm.stopBroadcast();

        _log(factory, vault, agent, guardian, priceMaxAge);
        _publish(
            Published({
                network: network,
                factory: address(factory),
                implementation: factory.implementation(),
                vault: vault,
                agent: agent,
                guardian: guardian,
                mandateHash: mandateHash,
                priceMaxAge: priceMaxAge
            })
        );
    }

    // ─────────────────────────────────────────────────────────────────────
    // Guards for anything that is not a throwaway fork
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Whether `network` is the throwaway local fork.
    /// @dev Exact match, and everything else counts as real. A typo like "base-forks" therefore gets
    ///      the *strict* configuration and trips the guards, rather than quietly deploying a vault
    ///      with its staleness checking off.
    function _isForkNetwork(string memory network) internal pure returns (bool) {
        return keccak256(bytes(network)) == keccak256(bytes(FORK_NETWORK));
    }

    /// @notice Staleness bound to use when `PRICE_MAX_AGE` is not set explicitly.
    function _defaultPriceMaxAge(string memory network) internal pure returns (uint256) {
        return _isForkNetwork(network) ? 0 : LIVE_PRICE_MAX_AGE;
    }

    /// @notice Which key signs the deploy.
    ///
    /// @dev **A fork deploy deliberately ignores `DEPLOYER_PRIVATE_KEY`.** `.env.example` defines
    ///      that variable as the funded *mainnet* wallet — "Fresh wallet, funded ~$20 + gas on Base"
    ///      — so it has no balance on a fresh fork by definition. Reading it here meant that merely
    ///      sourcing `.env`, which `scripts/*.sh` do and which any runbook would tell a human to do,
    ///      turned a working fork deploy into a failing one. That is a nasty trap: the deploy works
    ///      in a bare shell and fails in the documented one.
    ///
    ///      Set `FORK_DEPLOYER_PRIVATE_KEY` to override the anvil account on a fork; the mainnet key
    ///      stays reserved for real networks, which is what it was always documented to be.
    function _resolveDeployerKey(bool isFork) internal view returns (uint256) {
        return _chooseDeployerKey(
            isFork, vm.envOr("FORK_DEPLOYER_PRIVATE_KEY", uint256(0)), vm.envOr("DEPLOYER_PRIVATE_KEY", uint256(0))
        );
    }

    /// @notice The precedence rule on its own, with the environment factored out.
    /// @dev Pure so it can be tested exhaustively. Reading the variables inside made the tests
    ///      order-dependent, because `vm.setEnv` persists for the whole `forge test` process — one
    ///      test setting `FORK_DEPLOYER_PRIVATE_KEY` changed what a later test observed. Separating
    ///      the policy from the I/O fixes that at the root instead of sequencing around it.
    /// @param forkKeyOrZero    `FORK_DEPLOYER_PRIVATE_KEY`, or 0 if unset.
    /// @param mainnetKeyOrZero `DEPLOYER_PRIVATE_KEY`, or 0 if unset.
    function _chooseDeployerKey(bool isFork, uint256 forkKeyOrZero, uint256 mainnetKeyOrZero)
        internal
        pure
        returns (uint256)
    {
        if (isFork) return forkKeyOrZero != 0 ? forkKeyOrZero : ANVIL_ACCOUNT_0;
        return mainnetKeyOrZero != 0 ? mainnetKeyOrZero : ANVIL_ACCOUNT_0;
    }

    /// @notice Refuse to start a deploy the signer cannot pay for.
    /// @dev Turns "Internal EVM error during simulation" — which says nothing about the cause — into
    ///      a named error carrying the account and its balance.
    function _assertCanPayGas(address deployer, uint256 balance) internal pure {
        if (balance < MIN_DEPLOYER_BALANCE) {
            revert DeployerCannotPayGas(deployer, balance, MIN_DEPLOYER_BALANCE);
        }
    }

    /// @notice Refuse to deploy to a real network with fork-grade configuration.
    ///
    /// @dev Two mistakes this makes impossible, both of which are one forgotten env var away and
    ///      neither of which announces itself:
    ///
    ///      **An anvil account as agent, deployer or guardian.** Anvil's keys are published in
    ///      Foundry's documentation. A mainnet vault whose `AGENT_ROLE` is anvil account #1 can be
    ///      drained by anyone who has ever read those docs — and because the role graph is frozen at
    ///      genesis, it could not be revoked. The vault would have to be abandoned. The fork run
    ///      deliberately uses those keys, so the failure mode is simply forgetting to change them.
    ///
    ///      **Staleness checking left off.** `priceMaxAge = 0` is correct on a pinned fork and wrong
    ///      everywhere else: it makes `totalAssets()` trust a Chainlink answer of any age, so shares
    ///      would price off a frozen feed during exactly the volatility that makes a feed stall.
    ///      Also immutable after genesis.
    ///
    ///      Deliberately reverts rather than warns. A warning scrolls past in a broadcast log; this
    ///      is a real-money, one-shot, unfixable-afterwards decision.
    function _assertSafeForRealNetwork(
        string memory network,
        address deployer,
        address agent,
        address guardian,
        uint256 priceMaxAge
    ) internal pure {
        if (deployer == ANVIL_ADDRESS_0 || deployer == ANVIL_ADDRESS_1) {
            revert UnsafeAnvilKeyOnRealNetwork("DEPLOYER_PRIVATE_KEY", deployer);
        }
        if (agent == ANVIL_ADDRESS_0 || agent == ANVIL_ADDRESS_1) {
            revert UnsafeAnvilKeyOnRealNetwork("AGENT_ADDRESS", agent);
        }
        if (guardian == ANVIL_ADDRESS_0 || guardian == ANVIL_ADDRESS_1) {
            revert UnsafeAnvilKeyOnRealNetwork("GUARDIAN_ADDRESS", guardian);
        }
        if (priceMaxAge == 0) revert StalenessCheckDisabledOnRealNetwork(network);
    }

    // ─────────────────────────────────────────────────────────────────────
    // Configuration
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Contracts the agent may reach through `execute`.
    /// @dev Tokens are on this list deliberately: an `ExecutionPlan` step for
    ///      `USDC.approve(Permit2, …)` targets the token, not a venue (Lane D request #8, and the
    ///      shape of the golden fixture). Widening it later on a live vault is the guardian's job;
    ///      changing it for future vaults is `factory.setDefaultTarget`.
    function _allowlist() internal pure returns (address[] memory targets) {
        targets = new address[](7);
        targets[0] = AQUA;
        targets[1] = SWAPVM;
        targets[2] = UNIVERSAL_ROUTER;
        targets[3] = SWAP_ROUTER_02;
        targets[4] = PERMIT2;
        targets[5] = USDC;
        targets[6] = WETH;
    }

    /// @notice Non-base tokens the vault can price, and therefore the only ones it can safely hold.
    function _valuations() internal pure returns (ICuratedVault.TokenValuation[] memory v) {
        v = new ICuratedVault.TokenValuation[](1);
        v[0] = ICuratedVault.TokenValuation({token: WETH, feed: ETH_USD_FEED});
    }

    // ─────────────────────────────────────────────────────────────────────
    // Publishing
    // ─────────────────────────────────────────────────────────────────────

    /// @dev Grouped into a struct and split across helpers because Solidity's stack cannot hold
    ///      this many live locals at once — `serializeJson` keeps every intermediate alive.
    struct Published {
        string network;
        address factory;
        address implementation;
        address vault;
        address agent;
        address guardian;
        bytes32 mandateHash;
        uint256 priceMaxAge;
    }

    function _publish(Published memory p) internal {
        string memory root = "root";
        vm.serializeString(
            root,
            "_comment",
            "Written by contracts/script/Deploy.s.sol. Do not hand-edit - re-run the deploy. Every lane reads addresses from here instead of hardcoding them."
        );
        vm.serializeString(root, "network", p.network);
        vm.serializeUint(root, "chainId", block.chainid);
        vm.serializeUint(root, "blockNumber", block.number);
        vm.serializeUint(root, "deployedAt", block.timestamp);
        vm.serializeUint(root, "priceMaxAge", p.priceMaxAge);
        vm.serializeString(root, "contracts", _contractsJson(p));
        vm.serializeAddress(root, "vaults", _vaultList(p));
        vm.serializeString(root, "demoVault", _demoJson(p));
        vm.serializeString(root, "external", _externalJson());
        string memory out = vm.serializeString(root, "executeAllowlist", _allowlistJson());

        string memory path = string.concat("../deployments/", p.network, ".json");
        vm.writeJson(out, path);
        console2.log("published ->", path);
    }

    function _contractsJson(Published memory p) private returns (string memory) {
        string memory obj = "contracts";
        vm.serializeAddress(obj, "VaultFactory", p.factory);
        return vm.serializeAddress(obj, "CuratedVaultImplementation", p.implementation);
    }

    function _demoJson(Published memory p) private returns (string memory) {
        string memory obj = "demoVault";
        vm.serializeAddress(obj, "address", p.vault);
        vm.serializeAddress(obj, "asset", USDC);
        vm.serializeAddress(obj, "agent", p.agent);
        vm.serializeAddress(obj, "guardian", p.guardian);
        vm.serializeString(obj, "symbol", "cUSDC");
        vm.serializeUint(obj, "shareDecimals", 18);
        return vm.serializeBytes32(obj, "mandateHash", p.mandateHash);
    }

    function _externalJson() private returns (string memory) {
        string memory obj = "external";
        vm.serializeAddress(obj, "Aqua", AQUA);
        vm.serializeAddress(obj, "SwapVM", SWAPVM);
        vm.serializeAddress(obj, "UniswapUniversalRouter", UNIVERSAL_ROUTER);
        vm.serializeAddress(obj, "UniswapSwapRouter02", SWAP_ROUTER_02);
        vm.serializeAddress(obj, "Permit2", PERMIT2);
        vm.serializeAddress(obj, "USDC", USDC);
        vm.serializeAddress(obj, "WETH", WETH);
        return vm.serializeAddress(obj, "ChainlinkEthUsdFeed", ETH_USD_FEED);
    }

    function _allowlistJson() private returns (string memory) {
        return vm.serializeAddress("executeAllowlist", "targets", _allowlist());
    }

    function _vaultList(Published memory p) private pure returns (address[] memory list) {
        list = new address[](1);
        list[0] = p.vault;
    }

    function _log(VaultFactory factory, address vault, address agent, address guardian, uint256 priceMaxAge)
        internal
        view
    {
        console2.log("VaultFactory       ", address(factory));
        console2.log("Implementation     ", factory.implementation());
        console2.log("Demo vault         ", vault);
        console2.log("  agent            ", agent);
        console2.log("  guardian         ", guardian);
        console2.log("  priceMaxAge      ", priceMaxAge);
    }
}
