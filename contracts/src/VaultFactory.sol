// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Clones} from "@openzeppelin/contracts/proxy/Clones.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {CuratedVault} from "./CuratedVault.sol";
import {ICuratedVault} from "./interfaces/ICuratedVault.sol";
import {IVaultFactory} from "./interfaces/IVaultFactory.sol";

/// @title VaultFactory — one cloned vault per strategy.
///
/// @notice Deploys `CuratedVault` clones and holds the **default configuration** each new vault
///         copies at genesis: the target allowlist, the price-feed set, and the staleness bound.
///
/// @dev The mutable-template / immutable-instance split is the design's load-bearing idea.
///
///      Editable here, because addresses are still being discovered while five lanes build in
///      parallel — the Uniswap router target, for one, is confirmed against a live API response
///      rather than known up front. Frozen in the vault, because a live vault holds depositor money:
///      a mutable valuation set would let whoever controls it register a bogus feed and mint or
///      redeem shares at a manipulated price.
///
///      Changing a default never reaches a vault that already exists. To give an existing vault a
///      newly-discovered target, its guardian calls `setTargetAllowed` on the vault itself.
///
///      The factory also records **who a vault was created on behalf of** (`vaultsOf`,
///      `deployerOf`, and the `deployer` topic on `VaultCreated`). That record lives here rather
///      than on the vault for a reason: the vault must not be able to read it, so it cannot
///      accidentally become a permission. See `IVaultFactory.CreateParams.deployer`.
contract VaultFactory is Ownable, IVaultFactory {
    /// @notice The implementation every clone delegates to. Initializers are disabled on it.
    address public immutable implementation;

    address[] private _vaults;
    mapping(address vault => bool) private _isVault;

    /// @dev Attribution only. See `IVaultFactory.CreateParams.deployer` — a label, not an ACL.
    mapping(address deployer => address[]) private _vaultsOf;
    mapping(address vault => address) private _deployerOf;

    address[] private _defaultTargets;
    mapping(address target => bool) private _isDefaultTarget;

    address[] private _defaultValuedTokens;
    mapping(address token => address feed) private _defaultFeeds;

    uint256 private _defaultPriceMaxAge;

    /// @param owner_ Platform operator. May edit the defaults; has no power over any live vault.
    /// @param initialTargets Seed allowlist — the venues and tokens the agent may reach.
    /// @param initialValuations Seed price feeds for non-base tokens the agent may hold.
    /// @param initialPriceMaxAge Seconds. **0 disables the staleness check** — correct on a pinned
    ///        anvil fork, wrong on mainnet. See `ChainlinkPriceLib.readPrice`.
    constructor(
        address owner_,
        address[] memory initialTargets,
        ICuratedVault.TokenValuation[] memory initialValuations,
        uint256 initialPriceMaxAge
    ) Ownable(owner_) {
        implementation = address(new CuratedVault());

        for (uint256 i; i < initialTargets.length; ++i) {
            _setDefaultTarget(initialTargets[i], true);
        }
        for (uint256 i; i < initialValuations.length; ++i) {
            _setDefaultValuation(initialValuations[i].token, initialValuations[i].feed);
        }
        _defaultPriceMaxAge = initialPriceMaxAge;
        emit DefaultPriceMaxAgeSet(initialPriceMaxAge);
    }

    /// @inheritdoc IVaultFactory
    function createVault(CreateParams calldata params) external returns (address vault) {
        vault = Clones.clone(implementation);

        CuratedVault(vault).initialize(
            ICuratedVault.InitParams({
                asset: params.asset,
                name: params.name,
                symbol: params.symbol,
                agent: params.agent,
                guardian: params.guardian,
                mandateHash: params.mandateHash,
                allowedTargets: _defaultTargets,
                valuations: defaultValuations(),
                priceMaxAge: _defaultPriceMaxAge
            })
        );

        // Falling back to msg.sender rather than reverting keeps the field optional for the callers
        // that predate it, and keeps `deployerOf` total — every vault has an answer, never a null.
        address deployer = params.deployer == address(0) ? msg.sender : params.deployer;

        _vaults.push(vault);
        _isVault[vault] = true;
        _vaultsOf[deployer].push(vault);
        _deployerOf[vault] = deployer;

        emit VaultCreated(vault, params.asset, params.agent, params.mandateHash, deployer);
    }

    // ─────────────────────────────────────────────────────────────────────
    // Defaults — owner only
    // ─────────────────────────────────────────────────────────────────────

    /// @inheritdoc IVaultFactory
    function setDefaultTarget(address target, bool allowed) external onlyOwner {
        _setDefaultTarget(target, allowed);
    }

    /// @inheritdoc IVaultFactory
    /// @dev Passing `feed == address(0)` removes the token from the default valuation set.
    function setDefaultValuation(address token, address feed) external onlyOwner {
        _setDefaultValuation(token, feed);
    }

    /// @inheritdoc IVaultFactory
    function setDefaultPriceMaxAge(uint256 maxAge) external onlyOwner {
        _defaultPriceMaxAge = maxAge;
        emit DefaultPriceMaxAgeSet(maxAge);
    }

    function _setDefaultTarget(address target, bool allowed) private {
        if (target == address(0)) revert ZeroAddress();
        if (allowed == _isDefaultTarget[target]) return;

        _isDefaultTarget[target] = allowed;
        if (allowed) {
            _defaultTargets.push(target);
        } else {
            _removeFrom(_defaultTargets, target);
        }
        emit DefaultTargetSet(target, allowed);
    }

    function _setDefaultValuation(address token, address feed) private {
        if (token == address(0)) revert ZeroAddress();

        address current = _defaultFeeds[token];
        if (feed == address(0)) {
            if (current == address(0)) revert UnknownDefaultValuation(token);
            _removeFrom(_defaultValuedTokens, token);
        } else if (current == address(0)) {
            _defaultValuedTokens.push(token);
        }

        _defaultFeeds[token] = feed;
        emit DefaultValuationSet(token, feed);
    }

    /// @dev Swap-and-pop. Order of the default set is not part of the contract.
    function _removeFrom(address[] storage list, address value) private {
        uint256 n = list.length;
        for (uint256 i; i < n; ++i) {
            if (list[i] == value) {
                list[i] = list[n - 1];
                list.pop();
                return;
            }
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // Views
    // ─────────────────────────────────────────────────────────────────────

    /// @inheritdoc IVaultFactory
    function vaults() external view returns (address[] memory) {
        return _vaults;
    }

    /// @inheritdoc IVaultFactory
    function vaultCount() external view returns (uint256) {
        return _vaults.length;
    }

    /// @inheritdoc IVaultFactory
    function isVault(address vault) external view returns (bool) {
        return _isVault[vault];
    }

    /// @inheritdoc IVaultFactory
    function vaultsOf(address who) external view returns (address[] memory) {
        return _vaultsOf[who];
    }

    /// @inheritdoc IVaultFactory
    function deployerOf(address vault) external view returns (address) {
        return _deployerOf[vault];
    }

    /// @inheritdoc IVaultFactory
    function defaultTargets() external view returns (address[] memory) {
        return _defaultTargets;
    }

    /// @inheritdoc IVaultFactory
    function defaultValuations() public view returns (ICuratedVault.TokenValuation[] memory out) {
        uint256 n = _defaultValuedTokens.length;
        out = new ICuratedVault.TokenValuation[](n);
        for (uint256 i; i < n; ++i) {
            address token = _defaultValuedTokens[i];
            out[i] = ICuratedVault.TokenValuation({token: token, feed: _defaultFeeds[token]});
        }
    }

    /// @inheritdoc IVaultFactory
    function defaultPriceMaxAge() external view returns (uint256) {
        return _defaultPriceMaxAge;
    }
}
