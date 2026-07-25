// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";

import {CuratedVault} from "../src/CuratedVault.sol";
import {VaultFactory} from "../src/VaultFactory.sol";
import {IAggregatorV3} from "../src/interfaces/IAggregatorV3.sol";
import {ICuratedVault} from "../src/interfaces/ICuratedVault.sol";
import {ChainlinkPriceLib} from "../src/libraries/ChainlinkPriceLib.sol";

/// @title VerifyDeployment — is the thing on chain the thing we meant to deploy?
///
/// @notice Reads `deployments/<network>.json` and interrogates the **live** contracts it names.
///         Read-only: it never broadcasts, so it is safe to run against mainnet at any time.
///
/// ```bash
/// forge script script/VerifyDeployment.s.sol --rpc-url http://127.0.0.1:8540
/// DEPLOY_NETWORK=base-mainnet forge script script/VerifyDeployment.s.sol --rpc-url "$BASE_RPC_URL"
/// ```
///
/// @dev **This answers a different question from `check-deployment.sh`,** and both are needed.
///      That script asks *"is the deployed bytecode the source in this repo?"* — a question about
///      compilation. This asks *"is the deployed contract configured the way the published file
///      claims, and can it actually function?"* — a question about state. A vault can pass the first
///      and fail the second in every way that matters: right code, wrong agent; right code, an
///      allowlist missing the router every plan targets; right code, a feed that has stopped
///      answering so `totalAssets()` reverts and nobody can deposit or withdraw.
///
///      Every check reverts with a named error rather than logging a warning, because the only
///      reason to run this is as a gate — before the demo, before announcing an address to four
///      lanes, and before a single real deposit.
contract VerifyDeployment is Script {
    error NotAContract(string what, address account);
    error Mismatch(string what, address expected, address actual);
    error VaultNotRegisteredWithFactory(address vault);
    error WrongChain(uint256 published, uint256 actual);
    error AllowlistMissingTarget(address target);
    error AllowlistHasUnexpectedSize(uint256 published, uint256 onChain);
    error RoleNotHeld(string what, address account);
    error AdminRoleExists(address account);
    error RoleGraphIsNotFrozen(string what);
    error ValuationMissing(address token);
    error PausedSurfaceMissing();
    error VaultIsPaused();
    error MandateHashMismatch(bytes32 published, bytes32 onChain);
    error PriceMaxAgeMismatch(uint256 published, uint256 onChain);
    error DeployerNotRecorded(address vault);

    /// @dev An address with no role, no shares and no allowance — only ever used as the subject of a
    ///      zero-amount staticcall, so it never receives anything.
    address internal constant PROBE = 0x000000000000000000000000000000000000dEaD;

    string internal json;

    function run() external {
        string memory network = vm.envOr("DEPLOY_NETWORK", string("base-fork"));
        json = vm.readFile(string.concat("../deployments/", network, ".json"));

        console2.log("network            ", network);
        console2.log("chainId (live)     ", block.chainid);

        uint256 publishedChain = vm.parseJsonUint(json, ".chainId");
        if (publishedChain != block.chainid) revert WrongChain(publishedChain, block.chainid);

        VaultFactory factory = VaultFactory(_addr(".contracts.VaultFactory"));
        CuratedVault vault = CuratedVault(_addr(".demoVault.address"));

        _checkDeployedCode(factory, vault);
        _checkIdentity(factory, vault);
        _checkRoleGraph(vault);
        _checkAllowlist(vault);
        _checkValuationAndPricing(vault);
        _checkWave3Surface(factory, vault);

        console2.log("");
        console2.log("OK - every published claim holds against live state.");
    }

    // ─────────────────────────────────────────────────────────────────────

    function _checkDeployedCode(VaultFactory factory, CuratedVault vault) internal view {
        _requireContract("VaultFactory", address(factory));
        _requireContract("CuratedVaultImplementation", _addr(".contracts.CuratedVaultImplementation"));
        _requireContract("demoVault", address(vault));

        address published = _addr(".contracts.CuratedVaultImplementation");
        if (factory.implementation() != published) {
            revert Mismatch("implementation", published, factory.implementation());
        }
        // A clone that the factory does not recognise is a vault nothing indexes and nobody's
        // `isVault` check will accept — including Lane E's.
        if (!factory.isVault(address(vault))) revert VaultNotRegisteredWithFactory(address(vault));

        console2.log("code + registration  OK");
    }

    function _checkIdentity(VaultFactory factory, CuratedVault vault) internal view {
        _requireSame("asset", _addr(".demoVault.asset"), vault.asset());
        _requireSame("agent", _addr(".demoVault.agent"), vault.agent());
        _requireSame("guardian", _addr(".demoVault.guardian"), vault.guardian());

        bytes32 publishedMandate = vm.parseJsonBytes32(json, ".demoVault.mandateHash");
        if (vault.mandateHash() != publishedMandate) {
            revert MandateHashMismatch(publishedMandate, vault.mandateHash());
        }

        uint256 publishedMaxAge = vm.parseJsonUint(json, ".priceMaxAge");
        if (vault.priceMaxAge() != publishedMaxAge) {
            revert PriceMaxAgeMismatch(publishedMaxAge, vault.priceMaxAge());
        }

        // Attribution is a label and never an ACL (SECURITY.md §11), but a *missing* one means the
        // dashboard's "my vaults" silently shows nothing rather than failing.
        if (factory.deployerOf(address(vault)) == address(0)) revert DeployerNotRecorded(address(vault));

        console2.log("identity + mandate   OK");
    }

    /// @dev The claim `SECURITY.md` opens with, checked against the chain rather than the source.
    ///      Nobody holds admin, and all three mutation paths revert — including `renounceRole`,
    ///      which AccessControl allows by default and which would let the agent brick its own vault.
    function _checkRoleGraph(CuratedVault vault) internal view {
        if (!vault.hasRole(vault.AGENT_ROLE(), vault.agent())) revert RoleNotHeld("agent", vault.agent());
        if (!vault.hasRole(vault.GUARDIAN_ROLE(), vault.guardian())) {
            revert RoleNotHeld("guardian", vault.guardian());
        }
        if (vault.hasRole(0x00, vault.agent())) revert AdminRoleExists(vault.agent());
        if (vault.hasRole(0x00, vault.guardian())) revert AdminRoleExists(vault.guardian());
        if (vault.hasRole(0x00, msg.sender)) revert AdminRoleExists(msg.sender);

        _requireReverts("grantRole", abi.encodeCall(vault.grantRole, (vault.AGENT_ROLE(), msg.sender)), address(vault));
        _requireReverts(
            "revokeRole", abi.encodeCall(vault.revokeRole, (vault.AGENT_ROLE(), vault.agent())), address(vault)
        );
        _requireReverts(
            "renounceRole", abi.encodeCall(vault.renounceRole, (vault.AGENT_ROLE(), vault.agent())), address(vault)
        );

        console2.log("role graph frozen    OK");
    }

    /// @dev Set containment, not equality of order — the on-chain list is an `EnumerableSet` and its
    ///      order is not part of the contract. Size is compared separately so an *extra* target,
    ///      which set containment alone would not notice, still shows up.
    function _checkAllowlist(CuratedVault vault) internal view {
        address[] memory published = vm.parseJsonAddressArray(json, ".executeAllowlist.targets");
        address[] memory onChain = vault.allowedTargets();

        for (uint256 i; i < published.length; ++i) {
            if (!vault.isAllowedTarget(published[i])) revert AllowlistMissingTarget(published[i]);
            _requireContract("allowlisted target", published[i]);
        }
        if (onChain.length != published.length) {
            revert AllowlistHasUnexpectedSize(published.length, onChain.length);
        }

        console2.log("allowlist            OK -", published.length);
    }

    /// @dev The check that would have caught a dead feed before a depositor did. `readPrice` is the
    ///      same call `totalAssets()` makes, with the vault's own frozen `priceMaxAge`, so a pass
    ///      here means accounting works *right now* — and `totalAssets()` is then called for real,
    ///      because that is the function every deposit, withdrawal and share price goes through.
    function _checkValuationAndPricing(CuratedVault vault) internal view {
        address[] memory tokens = vault.valuedTokens();
        for (uint256 i; i < tokens.length; ++i) {
            address feed = vault.priceFeed(tokens[i]);
            if (feed == address(0)) revert ValuationMissing(tokens[i]);
            _requireContract("price feed", feed);
            ChainlinkPriceLib.readPrice(IAggregatorV3(feed), vault.priceMaxAge());
        }

        uint256 total = vault.totalAssets();
        ICuratedVault.Holding[] memory holdings = vault.holdings();

        console2.log("pricing              OK - totalAssets", total);
        console2.log("                          holdings   ", holdings.length);
    }

    /// @dev The reason this script exists at all today. A vault cloned from a pre-Wave-3
    ///      implementation does not merely report `paused() == false` — the function is absent, so
    ///      the call reverts. Lane B's optional-call probe coerces that to `false`, which is
    ///      byte-identical to a healthy unpaused vault. Without this check, "the guardian can halt
    ///      trading" would be demonstrated by a vault that silently ignores `pause()`.
    /// @dev **This one is not `view`, and that is deliberate — see the `redeemInKind` probe.** The
    ///      script still never broadcasts: only calls between `startBroadcast`/`stopBroadcast` are
    ///      sent, and there are none anywhere in this file. The probe executes in forge's simulation
    ///      against forked state and is discarded.
    function _checkWave3Surface(VaultFactory factory, CuratedVault vault) internal {
        (bool ok, bytes memory ret) = address(vault).staticcall(abi.encodeCall(vault.paused, ()));
        if (!ok || ret.length != 32) revert PausedSurfaceMissing();
        if (abi.decode(ret, (bool))) revert VaultIsPaused();

        // `redeemInKind` for zero shares moves no tokens, burns nothing and pays nobody — but it is
        // still a *write*: `_spendAllowance` and `_burn` both touch storage and emit even at zero,
        // so a staticcall probe reverts on a perfectly healthy vault and proves nothing. A real call
        // in simulation runs the whole payout path end to end instead, which is the stronger check.
        //
        // The probe address is an arbitrary constant rather than `address(this)`, which forge rejects
        // in scripts: script contracts are ephemeral and their address means nothing.
        (bool exits,) = address(vault).call(abi.encodeCall(vault.redeemInKind, (0, PROBE, PROBE)));
        if (!exits) revert PausedSurfaceMissing();

        // `vaultsOf` is what a dashboard calls instead of scanning logs.
        factory.vaultsOf(factory.deployerOf(address(vault)));

        console2.log("wave 3 surface       OK - pause + redeemInKind + attribution live");
    }

    // ─────────────────────────────────────────────────────────────────────

    function _addr(string memory key) internal view returns (address) {
        return vm.parseJsonAddress(json, key);
    }

    function _requireContract(string memory what, address account) internal view {
        if (account.code.length == 0) revert NotAContract(what, account);
    }

    function _requireSame(string memory what, address expected, address actual) internal pure {
        if (expected != actual) revert Mismatch(what, expected, actual);
    }

    /// @dev A frozen mutator must *fail*. Asserted with a raw call so a success is observable rather
    ///      than aborting this script with the callee's revert.
    function _requireReverts(string memory what, bytes memory data, address target) internal view {
        (bool ok,) = target.staticcall(data);
        if (ok) revert RoleGraphIsNotFrozen(what);
    }
}
