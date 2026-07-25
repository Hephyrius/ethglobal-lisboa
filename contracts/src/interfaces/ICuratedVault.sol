// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ICuratedVault — the surface every other lane codes against.
/// @notice An ERC-4626 vault whose curator is an autonomous agent. The vault is the **sole
///         custodian** of all capital (Pattern 1): assets never leave it, not even while an Aqua
///         strategy is open, so `totalAssets()` is always the complete picture.
///
/// @dev The integration seam. `execute` takes an opaque `data` blob against an allowlisted `target`,
///      so venue adapters build any calldata off-chain and this contract never learns what a venue
///      is. A new venue is a new off-chain adapter, never a contract change.
///
///      Read this alongside `contracts/README.md`, which is the authoritative usage doc.
interface ICuratedVault {
    // ─────────────────────────────────────────────────────────────────────
    // Types
    // ─────────────────────────────────────────────────────────────────────

    /// @notice One step of an `ExecutionPlan` (see `packages/schema/execution-plan.schema.json`).
    /// @dev Field order and types mirror the JSON schema's `step` exactly, so an off-chain adapter
    ///      can encode a plan without a translation layer.
    struct Call {
        address target;
        uint256 value;
        bytes data;
    }

    /// @notice A non-base token the vault may hold, and the Chainlink feed that prices it.
    /// @dev Registered once at genesis and immutable thereafter — see `README.md` §Invariants.
    ///      A token absent from this set is invisible to `totalAssets()`.
    struct TokenValuation {
        address token;
        address feed;
    }

    /// @notice Genesis configuration. Passed by the factory in the same transaction as the clone.
    struct InitParams {
        /// ERC-4626 accounting asset. USDC on Base for the demo.
        address asset;
        string name;
        string symbol;
        /// Holder of `AGENT_ROLE`. Executes directly, with no human override — that is the trust model.
        address agent;
        /// Holder of `GUARDIAN_ROLE`. May widen or narrow the target allowlist and nothing else.
        address guardian;
        /// keccak256 of the canonical mandate JSON, recorded so a depositor can verify the mandate
        /// they were shown is the one this vault was created with.
        bytes32 mandateHash;
        /// Contracts the agent may reach through `execute`. Snapshotted from the factory default.
        address[] allowedTargets;
        /// Non-base tokens and their price feeds. Immutable after this call.
        TokenValuation[] valuations;
        /// Maximum age of a Chainlink answer, in seconds. **0 disables the staleness check** —
        /// required on a pinned anvil fork, where feed `updatedAt` is frozen at the fork block
        /// while `block.timestamp` keeps advancing.
        uint256 priceMaxAge;
    }

    /// @notice One line of `VaultState.holdings`, computed on-chain so the harness and the dApp
    ///         never disagree with the contract about what a position is worth.
    struct Holding {
        address token;
        uint8 decimals;
        uint256 balance;
        /// Valued through the same feed and the same math `totalAssets()` uses.
        uint256 valueInAsset;
    }

    // ─────────────────────────────────────────────────────────────────────
    // Events
    // ─────────────────────────────────────────────────────────────────────

    event VaultInitialized(
        address indexed asset, address indexed agent, address indexed guardian, bytes32 mandateHash
    );
    /// @dev `selector` is indexed so a decision feed can filter by call type without decoding data.
    event Executed(address indexed target, bytes4 indexed selector, uint256 value);
    event VenueApproved(address indexed token, address indexed spender, uint256 amount);
    event TargetAllowed(address indexed target, bool allowed);

    // ─────────────────────────────────────────────────────────────────────
    // Errors
    // ─────────────────────────────────────────────────────────────────────

    error TargetNotAllowed(address target);
    error SpenderNotAllowed(address spender);
    error EmptyBatch();
    error ZeroAddress();
    error DuplicateValuation(address token);
    /// @dev Thrown by `renounceRole`. The role graph is frozen at genesis, renunciation included —
    ///      otherwise the agent could brick its own vault.
    error RolesAreFrozen();

    // ─────────────────────────────────────────────────────────────────────
    // Agent surface — AGENT_ROLE only
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Perform one arbitrary call from the vault.
    /// @param target Must be on the allowlist, or this reverts with `TargetNotAllowed`.
    /// @param value  Native ETH in wei. The vault holds no ETH (it has no `receive()`), so in
    ///               practice this is always 0 — see README §Invariants.
    /// @param data   Opaque ABI-encoded calldata. The vault does not inspect it.
    /// @return The raw return data of the call. Reverts bubble up with the callee's own revert data.
    function execute(address target, uint256 value, bytes calldata data) external returns (bytes memory);

    /// @notice Perform a sequence of calls atomically — the on-chain form of one `ExecutionPlan`.
    /// @dev Preferred over N separate `execute` transactions: an `ExecutionPlan` is ordered
    ///      (approve, then swap) and all-or-nothing here, so a plan can never land half-applied.
    function executeBatch(Call[] calldata calls) external returns (bytes[] memory);

    /// @notice Set an ERC-20 allowance from the vault to a venue.
    /// @dev Equivalent to `execute(token, 0, approve(spender, amount))` when `token` is itself
    ///      allowlisted, but expressed as a narrow, self-documenting call: `spender` is checked
    ///      against the allowlist, and no arbitrary calldata reaches the token.
    ///      Handles non-standard tokens that require a reset-to-zero before re-approval.
    function approveVenue(address token, address spender, uint256 amount) external;

    // ─────────────────────────────────────────────────────────────────────
    // Guardian surface — GUARDIAN_ROLE only
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Add or remove a target from this vault's allowlist.
    /// @dev The guardian's *only* power. It cannot move funds, replace the agent, or alter
    ///      valuation, and only `AGENT_ROLE` can call `execute` — so widening the list grants the
    ///      guardian nothing it could exploit alone. Accepted residual risk: a guardian narrowing
    ///      the list can grief a rebalance. Liveness, not custody. README §Invariants.
    function setTargetAllowed(address target, bool allowed) external;

    // ─────────────────────────────────────────────────────────────────────
    // Views
    // ─────────────────────────────────────────────────────────────────────

    function agent() external view returns (address);
    function guardian() external view returns (address);
    function mandateHash() external view returns (bytes32);
    function priceMaxAge() external view returns (uint256);

    function isAllowedTarget(address target) external view returns (bool);
    /// @notice The full allowlist. Lane D validates `ExecutionPlan.steps[].target` against this.
    function allowedTargets() external view returns (address[] memory);

    /// @notice Non-base tokens registered for valuation, in registration order.
    function valuedTokens() external view returns (address[] memory);
    /// @notice Chainlink feed for `token`, or `address(0)` if unregistered.
    function priceFeed(address token) external view returns (address);

    /// @notice Every token the vault holds, priced — one call, so the harness does not need N+1
    ///         round-trips to build a `VaultState`. Index 0 is always the base asset.
    function holdings() external view returns (Holding[] memory);
}
