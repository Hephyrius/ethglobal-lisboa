// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ICuratedVault} from "./ICuratedVault.sol";

/// @title IVaultFactory — one vault per strategy, cloned from a single implementation.
/// @notice Holds the **mutable default configuration** (target allowlist, valuation set, price
///         staleness bound) that every new vault snapshots and then freezes forever.
///
/// @dev That split is the whole point: the template stays editable, because a venue address can
///      still be discovered mid-build; a live vault holding depositor money does not, because a
///      mutable valuation set would let its owner mint or burn shares at a manipulated price.
interface IVaultFactory {
    /// @notice Emitted once per vault. This is the event indexers and the dApp key off.
    event VaultCreated(address indexed vault, address indexed asset, address indexed agent, bytes32 mandateHash);
    event DefaultTargetSet(address indexed target, bool allowed);
    event DefaultValuationSet(address indexed token, address indexed feed);
    event DefaultPriceMaxAgeSet(uint256 priceMaxAge);

    error ZeroAddress();
    error UnknownDefaultValuation(address token);

    /// @notice Parameters that differ per vault. Everything else is snapshotted from the defaults.
    struct CreateParams {
        address asset;
        string name;
        string symbol;
        address agent;
        address guardian;
        bytes32 mandateHash;
    }

    /// @notice Clone, initialize and register a new vault.
    /// @dev The clone's allowlist and valuation set are copied from the factory defaults **at this
    ///      moment**. Later changes to the defaults do not reach vaults already created.
    /// @return vault The new vault's address.
    function createVault(CreateParams calldata params) external returns (address vault);

    /// @notice The implementation all clones delegate to. Never initialized, never holds funds.
    function implementation() external view returns (address);

    /// @notice Every vault this factory has created, in creation order.
    function vaults() external view returns (address[] memory);
    function vaultCount() external view returns (uint256);
    function isVault(address vault) external view returns (bool);

    /// @notice Defaults handed to the next vault created.
    function defaultTargets() external view returns (address[] memory);
    function defaultValuations() external view returns (ICuratedVault.TokenValuation[] memory);
    function defaultPriceMaxAge() external view returns (uint256);

    // ── owner-only ───────────────────────────────────────────────────────
    function setDefaultTarget(address target, bool allowed) external;
    function setDefaultValuation(address token, address feed) external;
    function setDefaultPriceMaxAge(uint256 maxAge) external;
}
