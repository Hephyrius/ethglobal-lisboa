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

    /// @dev Anvil's first account. Public knowledge and worthless — the default exists so a fork
    ///      deploy needs no configuration at all. A mainnet run must set DEPLOYER_PRIVATE_KEY.
    uint256 internal constant ANVIL_ACCOUNT_0 = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;
    address internal constant ANVIL_ADDRESS_1 = 0x70997970C51812dc3A010C7d01b50e0d17dc79C8;

    function run() external {
        string memory network = vm.envOr("DEPLOY_NETWORK", string("base-fork"));
        uint256 deployerKey = vm.envOr("DEPLOYER_PRIVATE_KEY", ANVIL_ACCOUNT_0);
        address deployer = vm.addr(deployerKey);

        address agent = vm.envOr("AGENT_ADDRESS", ANVIL_ADDRESS_1);
        address guardian = vm.envOr("GUARDIAN_ADDRESS", deployer);

        // 0 disables the Chainlink staleness check. Correct on a pinned fork, where the forked
        // feed's `updatedAt` is frozen while block.timestamp advances; wrong on mainnet, so the
        // mainnet run is expected to pass 3600. See ChainlinkPriceLib.readPrice.
        uint256 priceMaxAge = vm.envOr("PRICE_MAX_AGE", uint256(0));

        bytes32 mandateHash = vm.envOr("MANDATE_HASH", keccak256("demo-mandate-v1"));

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
                mandateHash: mandateHash
            })
        );

        vm.stopBroadcast();

        _log(factory, vault, agent, guardian, priceMaxAge);
        _publish(network, factory, vault, agent, guardian, mandateHash, priceMaxAge);
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

    function _publish(
        string memory network,
        VaultFactory factory,
        address vault,
        address agent,
        address guardian,
        bytes32 mandateHash,
        uint256 priceMaxAge
    ) internal {
        string memory contractsObj = "contracts";
        vm.serializeAddress(contractsObj, "VaultFactory", address(factory));
        string memory contractsJson =
            vm.serializeAddress(contractsObj, "CuratedVaultImplementation", factory.implementation());

        string memory externalObj = "external";
        vm.serializeAddress(externalObj, "Aqua", AQUA);
        vm.serializeAddress(externalObj, "SwapVM", SWAPVM);
        vm.serializeAddress(externalObj, "UniswapUniversalRouter", UNIVERSAL_ROUTER);
        vm.serializeAddress(externalObj, "UniswapSwapRouter02", SWAP_ROUTER_02);
        vm.serializeAddress(externalObj, "Permit2", PERMIT2);
        vm.serializeAddress(externalObj, "USDC", USDC);
        vm.serializeAddress(externalObj, "WETH", WETH);
        string memory externalJson = vm.serializeAddress(externalObj, "ChainlinkEthUsdFeed", ETH_USD_FEED);

        string memory demoObj = "demoVault";
        vm.serializeAddress(demoObj, "address", vault);
        vm.serializeAddress(demoObj, "asset", USDC);
        vm.serializeAddress(demoObj, "agent", agent);
        vm.serializeAddress(demoObj, "guardian", guardian);
        vm.serializeString(demoObj, "symbol", "cUSDC");
        vm.serializeUint(demoObj, "shareDecimals", 18);
        string memory demoJson = vm.serializeBytes32(demoObj, "mandateHash", mandateHash);

        address[] memory vaultList = new address[](1);
        vaultList[0] = vault;

        string memory allowlistObj = "executeAllowlist";
        string memory allowlistJson = vm.serializeAddress(allowlistObj, "targets", _allowlist());

        string memory root = "root";
        vm.serializeString(
            root,
            "_comment",
            "Written by contracts/script/Deploy.s.sol. Do not hand-edit - re-run the deploy. Every lane reads addresses from here instead of hardcoding them."
        );
        vm.serializeString(root, "network", network);
        vm.serializeUint(root, "chainId", block.chainid);
        vm.serializeUint(root, "blockNumber", block.number);
        vm.serializeUint(root, "deployedAt", block.timestamp);
        vm.serializeUint(root, "priceMaxAge", priceMaxAge);
        vm.serializeString(root, "contracts", contractsJson);
        vm.serializeAddress(root, "vaults", vaultList);
        vm.serializeString(root, "demoVault", demoJson);
        vm.serializeString(root, "external", externalJson);
        string memory out = vm.serializeString(root, "executeAllowlist", allowlistJson);

        string memory path = string.concat("../deployments/", network, ".json");
        vm.writeJson(out, path);
        console2.log("published ->", path);
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
