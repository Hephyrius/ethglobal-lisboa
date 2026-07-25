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
    ///
    /// @dev `agent` is deliberately **not** indexed, though it once was. An event has three topic
    ///      slots and `deployer` needed one; at genesis every vault is created by the same agent key,
    ///      so filtering on it selects the entire set — an index that indexes nothing. `asset` keeps
    ///      its slot because "every USDC vault" is a filter someone will actually run.
    ///
    ///      `deployer` is **asserted, not proven** — see `CreateParams.deployer`.
    event VaultCreated(
        address indexed vault, address indexed asset, address agent, bytes32 mandateHash, address indexed deployer
    );
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
        /// Who asked for this vault. **A label, never an authorization primitive.**
        ///
        /// The agent submits `createVault`, so `msg.sender` records the agent, not the human who
        /// clicked. This field carries that human's address instead — but it is *asserted by the
        /// submitter*, not proven by a signature, and anyone may call `createVault` with any value
        /// here. It confers no power over the vault: nothing on-chain reads it, and the vault
        /// itself never learns it. Safe for "show me the vaults I deployed"; unsafe for anything
        /// that decides who may do what. `SECURITY.md` §11.
        ///
        /// `address(0)` records `msg.sender`, so the mapping is never null.
        address deployer;
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

    /// @notice Vaults created with `CreateParams.deployer == who`, in creation order.
    /// @dev Convenience over the `VaultCreated` topic filter, so a dApp can answer "my vaults" with
    ///      one `eth_call` instead of a log query over a block range. The event remains the source
    ///      of truth; this is a cache of it that cannot disagree, because both are written in the
    ///      same statement. Read `CreateParams.deployer` before trusting either for anything but
    ///      display.
    function vaultsOf(address who) external view returns (address[] memory);

    /// @notice Who `vault` was created on behalf of, or `address(0)` if this factory did not make it.
    function deployerOf(address vault) external view returns (address);

    /// @notice Defaults handed to the next vault created.
    function defaultTargets() external view returns (address[] memory);
    function defaultValuations() external view returns (ICuratedVault.TokenValuation[] memory);
    function defaultPriceMaxAge() external view returns (uint256);

    // ── owner-only ───────────────────────────────────────────────────────
    function setDefaultTarget(address target, bool allowed) external;
    function setDefaultValuation(address token, address feed) external;
    function setDefaultPriceMaxAge(uint256 maxAge) external;
}
