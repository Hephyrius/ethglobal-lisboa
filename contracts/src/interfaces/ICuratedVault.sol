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

    /// @notice One token paid out by `redeemInKind`. Index 0 is always the base asset, matching
    ///         `Holding[]`.
    struct InKindPayout {
        address token;
        uint256 amount;
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

    /// @dev Named for what it does, not for the OpenZeppelin convention it resembles. A log line
    ///      reading `Paused` invites the reading "the vault is frozen and my money is stuck", which
    ///      is the exact opposite of the truth: `withdraw` and `redeem` are never pausable.
    event TradingPaused(address indexed guardian);
    event TradingUnpaused(address indexed guardian);

    /// @dev Emitted by `redeemInKind`. `payouts[0]` is the base asset. The share burn is visible as
    ///      the usual ERC-20 `Transfer` to the zero address; no ERC-4626 `Withdraw` event is emitted
    ///      because there is no single `assets` figure that would be true.
    event RedeemedInKind(
        address indexed caller, address indexed receiver, address indexed owner, uint256 shares, InKindPayout[] payouts
    );

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

    error AlreadyPaused();
    error NotPaused();

    /// @dev Wind-down direction, base-asset leg. The vault may not end a paused call holding less
    ///      cash than it started with.
    error WindDownWouldSpendBaseAsset(uint256 balanceBefore, uint256 balanceAfter);
    /// @dev Wind-down direction, holdings leg. The vault may not end a paused call holding *more* of
    ///      any registered non-base token than it started with.
    error WindDownWouldIncreaseHolding(address token, uint256 balanceBefore, uint256 balanceAfter);

    // ─────────────────────────────────────────────────────────────────────
    // Genesis
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Configure a freshly-cloned vault. Callable exactly once, by the factory, in the same
    ///         transaction as the clone.
    /// @dev Everything in `InitParams` is immutable afterwards except the target allowlist, which
    ///      only `GUARDIAN_ROLE` may change. `DEFAULT_ADMIN_ROLE` is never granted, so the role
    ///      assignments made here are permanent.
    function initialize(InitParams calldata params) external;

    // ─────────────────────────────────────────────────────────────────────
    // Agent surface — AGENT_ROLE only
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Perform one arbitrary call from the vault.
    /// @dev While the vault is `paused`, this still works but the *result* is checked: see
    ///      `executeBatch` for the wind-down rule, which applies identically to a batch of one.
    /// @param target Must be on the allowlist, or this reverts with `TargetNotAllowed`.
    /// @param value  Native ETH in wei. The vault holds no ETH (it has no `receive()`), so in
    ///               practice this is always 0 — see README §Invariants.
    /// @param data   Opaque ABI-encoded calldata. The vault does not inspect it.
    /// @return The raw return data of the call. Reverts bubble up with the callee's own revert data.
    function execute(address target, uint256 value, bytes calldata data) external returns (bytes memory);

    /// @notice Perform a sequence of calls atomically — the on-chain form of one `ExecutionPlan`.
    /// @dev Preferred over N separate `execute` transactions: an `ExecutionPlan` is ordered
    ///      (approve, then swap) and all-or-nothing here, so a plan can never land half-applied.
    ///
    ///      **While `paused`, the batch must move the book toward cash.** Measured once, at the end:
    ///      the base-asset balance must not have decreased, and no registered non-base balance may
    ///      have increased. Selling is permitted; buying is not. Intermediate state is unconstrained,
    ///      so a multi-hop route that transiently holds a third token is fine — only the net effect
    ///      is judged. Two consequences worth stating plainly:
    ///
    ///      - The rule constrains **direction, not price.** A batch that dumps WETH for one wei of
    ///        USDC satisfies it. What bounds execution quality is `minOut` in the calldata and the
    ///        harness's slippage gate, exactly as when unpaused.
    ///      - It is compositional. Every paused call individually leaves cash non-decreasing and
    ///        every holding non-increasing, so *any sequence* of them does too. The book can only
    ///        converge on the base asset for as long as the pause lasts.
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
    /// @dev One of the guardian's two powers. It cannot move funds, replace the agent, or alter
    ///      valuation, and only `AGENT_ROLE` can call `execute` — so widening the list grants the
    ///      guardian nothing it could exploit alone. Accepted residual risk: a guardian narrowing
    ///      the list can grief a rebalance. Liveness, not custody. README §Invariants.
    function setTargetAllowed(address target, bool allowed) external;

    /// @notice Put the vault into wind-down: the agent may still trade, but only toward the base
    ///         asset. **Withdrawals are not affected and cannot be.**
    ///
    /// @dev This narrows a power the guardian already had rather than granting a new one — a
    ///      guardian who called `setTargetAllowed(t, false)` for every target had already stopped
    ///      all trading, one transaction at a time and invisibly. `pause` does it atomically, emits
    ///      an event the dashboard can explain, and leaves the agent able to *unwind* rather than
    ///      merely frozen.
    ///
    ///      What the guardian gains: "stop increasing, start decreasing". What it does not gain:
    ///      the ability to name a trade, choose a moment to liquidate, or touch anyone's exit. The
    ///      agent still chooses every route and every size, under the same allowlist.
    function pause() external;

    /// @notice Leave wind-down. Ordinary trading resumes.
    function unpause() external;

    // ─────────────────────────────────────────────────────────────────────
    // Exits — permissionless, and never pausable
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Burn `shares` and receive a pro-rata slice of **every** token the vault holds, rather
    ///         than the base asset.
    ///
    /// @dev The unconditional exit. `redeem` pays in one asset and therefore depends on the vault
    ///      holding enough of it — which, once the agent has rotated into WETH, it may not
    ///      (`SECURITY.md` §10: a solvent vault whose redemption reverts from the ERC-20). This path
    ///      reads no oracle, touches no venue, needs no liquidity and cannot revert for want of any:
    ///      it hands over a fraction of what is already there.
    ///
    ///      Priced with the same virtual-share denominator as `previewRedeem`, so it is never the
    ///      more generous of the two exits — the emergency door is not an economic bypass of the
    ///      front one. Callable whether or not the vault is paused; gating the unconditional exit
    ///      behind the guardian's switch would hand the guardian power over withdrawals, which is
    ///      the one thing `pause` must never do.
    ///
    ///      Tokens outside the valuation set are not paid out, because the vault cannot enumerate
    ///      them. Same blind spot as `totalAssets()`, same mitigation: the mandate confines the
    ///      agent to registered tokens.
    ///
    /// @param shares   Shares to burn. `msg.sender` must be `owner` or hold an allowance.
    /// @param receiver Recipient of every payout.
    /// @param owner    Whose shares are burned.
    /// @return payouts One entry per registered token, index 0 the base asset. Zero amounts are
    ///         reported but not transferred.
    function redeemInKind(uint256 shares, address receiver, address owner)
        external
        returns (InKindPayout[] memory payouts);

    // ─────────────────────────────────────────────────────────────────────
    // Views
    // ─────────────────────────────────────────────────────────────────────

    function agent() external view returns (address);
    function guardian() external view returns (address);
    function mandateHash() external view returns (bytes32);
    function priceMaxAge() external view returns (uint256);

    /// @notice True while the vault is in wind-down. Backs `VaultState.paused`.
    /// @dev Read it as *"the agent may only sell"*, never as *"withdrawals are suspended"*. Nothing
    ///      the guardian can do suspends a withdrawal.
    function paused() external view returns (bool);

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
