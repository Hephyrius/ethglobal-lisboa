// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC4626Upgradeable} from
    "@openzeppelin/contracts-upgradeable/token/ERC20/extensions/ERC4626Upgradeable.sol";
import {AccessControlUpgradeable} from "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import {ReentrancyGuardUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Address} from "@openzeppelin/contracts/utils/Address.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";
import {EnumerableSet} from "@openzeppelin/contracts/utils/structs/EnumerableSet.sol";

import {ICuratedVault} from "./interfaces/ICuratedVault.sol";
import {IAggregatorV3} from "./interfaces/IAggregatorV3.sol";
import {ChainlinkPriceLib} from "./libraries/ChainlinkPriceLib.sol";

/// @title CuratedVault — an ERC-4626 vault curated by an autonomous agent.
///
/// @notice Depositors hold shares; an off-chain LLM agent decides what the vault holds. The vault is
///         the **sole custodian** of every asset at all times (Pattern 1) — capital never leaves it,
///         not even while an Aqua strategy is open, because Aqua tracks virtual balances against
///         tokens that stay in the maker's wallet. `balanceOf(vault)` is therefore the complete
///         position picture, and `totalAssets()` is honest without reading any venue's state.
///
/// @dev **Trust model, stated up front.** The agent holds a key and executes directly. Nothing
///      on-chain enforces the mandate — it lives off-chain and is soft. That is a deliberate,
///      locked decision (`plans/initiate_plan.md` §2), not an oversight. What *is* enforced
///      on-chain is a blast radius: the agent may only reach contracts on this vault's allowlist.
///
///      **What the guardian can do, exactly.** Two things, and no more. It may edit the target
///      allowlist (`setTargetAllowed`), and it may put the vault into wind-down (`pause`), after
///      which the agent may still trade but only in the direction of the base asset — the contract
///      checks the balances, not the intent. That is a narrowing of a power the guardian always
///      had: flipping every target off, one transaction at a time, already stopped all trading.
///
///      **What the guardian cannot do, and what no role here can do.** It cannot move a single
///      token, name a trade, choose when a position is sold, replace the agent, alter the valuation
///      set, or reach anyone's shares. Above all it **cannot touch an exit**: `withdraw`, `redeem`
///      and `redeemInKind` are permissionless, unpausable, and stay that way in every state this
///      contract can be in. A guardian able to freeze depositor exits would hold strictly more
///      power than the agent it exists to contain, which is why that boundary is a test
///      (`test_withdrawalSucceedsWhilePaused`) and not a promise.
///
///      There is still no upgrade path, no admin, and no way for anyone to seize funds.
///
///      The role graph is frozen at genesis. `DEFAULT_ADMIN_ROLE` is never granted to anyone, and
///      granting, revoking and renouncing all revert. Nobody can replace the agent; nobody can
///      award themselves its powers.
///
///      Deployed as an EIP-1167 clone by `VaultFactory`, hence the initializer pattern. The vault is
///      **not** upgradeable: there is no proxy admin and no implementation slot to rewrite.
contract CuratedVault is ERC4626Upgradeable, AccessControlUpgradeable, ReentrancyGuardUpgradeable, ICuratedVault {
    using EnumerableSet for EnumerableSet.AddressSet;
    using SafeERC20 for IERC20;

    /// @notice The curator. Sole holder, forever — this key moves the money.
    bytes32 public constant AGENT_ROLE = keccak256("AGENT_ROLE");
    /// @notice May edit the target allowlist and nothing else. See `setTargetAllowed`.
    bytes32 public constant GUARDIAN_ROLE = keccak256("GUARDIAN_ROLE");

    /// @dev Cached at registration so `totalAssets()` costs no extra staticcalls per token.
    struct Valuation {
        address feed;
        uint8 feedDecimals;
        uint8 tokenDecimals;
    }

    address private _agent;
    address private _guardian;
    bytes32 private _mandateHash;
    uint256 private _priceMaxAge;
    uint8 private _assetDecimals;
    /// @dev Wind-down flag. Packs into the same slot as `_assetDecimals`.
    bool private _paused;

    EnumerableSet.AddressSet private _allowedTargets;
    address[] private _valuedTokens;
    mapping(address token => Valuation) private _valuations;

    /// @dev Locks the implementation so nobody can initialize it and pose as a real vault. Clones
    ///      get their own storage and are unaffected.
    constructor() {
        _disableInitializers();
    }

    // ─────────────────────────────────────────────────────────────────────
    // Genesis
    // ─────────────────────────────────────────────────────────────────────

    /// @inheritdoc ICuratedVault
    /// @dev Everything configured here is immutable for the life of the vault, except the target
    ///      allowlist. See the contract-level note for why that one exception is safe.
    function initialize(InitParams calldata p) external initializer {
        if (p.asset == address(0) || p.agent == address(0) || p.guardian == address(0)) revert ZeroAddress();

        __ERC20_init(p.name, p.symbol);
        __ERC4626_init(IERC20(p.asset));
        __AccessControl_init();
        __ReentrancyGuard_init();

        _agent = p.agent;
        _guardian = p.guardian;
        _mandateHash = p.mandateHash;
        _priceMaxAge = p.priceMaxAge;
        _assetDecimals = _tryDecimals(p.asset);

        // DEFAULT_ADMIN_ROLE is deliberately granted to nobody. With no admin, and with
        // grant/revoke/renounce overridden to revert, these two assignments are permanent.
        _grantRole(AGENT_ROLE, p.agent);
        _grantRole(GUARDIAN_ROLE, p.guardian);

        for (uint256 i; i < p.allowedTargets.length; ++i) {
            address target = p.allowedTargets[i];
            if (target == address(0)) revert ZeroAddress();
            if (_allowedTargets.add(target)) emit TargetAllowed(target, true);
        }

        for (uint256 i; i < p.valuations.length; ++i) {
            TokenValuation calldata v = p.valuations[i];
            if (v.token == address(0) || v.feed == address(0)) revert ZeroAddress();
            if (v.token == p.asset || _valuations[v.token].feed != address(0)) {
                revert DuplicateValuation(v.token);
            }
            _valuations[v.token] = Valuation({
                feed: v.feed,
                feedDecimals: IAggregatorV3(v.feed).decimals(),
                tokenDecimals: _tryDecimals(v.token)
            });
            _valuedTokens.push(v.token);
        }

        emit VaultInitialized(p.asset, p.agent, p.guardian, p.mandateHash);
    }

    // ─────────────────────────────────────────────────────────────────────
    // Agent surface
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Snapshot the book before an agent call and, if the vault is winding down, refuse the
    ///         call unless it left the book closer to cash.
    ///
    /// @dev Measured once around the whole call rather than per step, which is what lets a multi-hop
    ///      route hold an intermediate token without tripping the rule.
    ///
    ///      The `nonReentrant` guard on the entry points is load-bearing here and not merely
    ///      belt-and-braces: without it a venue could call back into `deposit` mid-batch, raise the
    ///      base-asset balance with a depositor's own money, and satisfy the direction check with a
    ///      purchase.
    modifier windDownDirection() {
        uint256[] memory before = _bookIfPaused();
        _;
        _requireMovedTowardBase(before);
    }

    /// @inheritdoc ICuratedVault
    function execute(address target, uint256 value, bytes calldata data)
        external
        onlyRole(AGENT_ROLE)
        nonReentrant
        windDownDirection
        returns (bytes memory)
    {
        return _call(target, value, data);
    }

    /// @inheritdoc ICuratedVault
    function executeBatch(Call[] calldata calls)
        external
        onlyRole(AGENT_ROLE)
        nonReentrant
        windDownDirection
        returns (bytes[] memory results)
    {
        uint256 n = calls.length;
        if (n == 0) revert EmptyBatch();

        results = new bytes[](n);
        for (uint256 i; i < n; ++i) {
            results[i] = _call(calls[i].target, calls[i].value, calls[i].data);
        }
    }

    /// @inheritdoc ICuratedVault
    /// @dev Deliberately **not** subject to the wind-down direction rule, because selling a holding
    ///      through a router requires approving it first — a wind-down that could not approve could
    ///      not unwind. An approval moves nothing by itself, and the spender must still be
    ///      allowlisted. The residual is stated in `SECURITY.md` §12: a compromised agent can grant
    ///      an allowance to an allowlisted venue and have it pulled in a later transaction, which
    ///      the direction rule never sees. That exposure is identical paused or not.
    function approveVenue(address token, address spender, uint256 amount) external onlyRole(AGENT_ROLE) nonReentrant {
        if (!_allowedTargets.contains(spender)) revert SpenderNotAllowed(spender);
        // forceApprove, not approve: some tokens (USDT-family) reject a non-zero → non-zero change.
        IERC20(token).forceApprove(spender, amount);
        emit VenueApproved(token, spender, amount);
    }

    /// @dev Reverts bubble the callee's own revert data, so a failed venue call is diagnosable from
    ///      the trace instead of surfacing as an opaque failure.
    function _call(address target, uint256 value, bytes memory data) private returns (bytes memory ret) {
        if (!_allowedTargets.contains(target)) revert TargetNotAllowed(target);
        ret = Address.functionCallWithValue(target, data, value);
        emit Executed(target, _selectorOf(data), value);
    }

    // ─────────────────────────────────────────────────────────────────────
    // Guardian surface
    // ─────────────────────────────────────────────────────────────────────

    /// @inheritdoc ICuratedVault
    function setTargetAllowed(address target, bool allowed) external onlyRole(GUARDIAN_ROLE) {
        if (target == address(0)) revert ZeroAddress();
        bool changed = allowed ? _allowedTargets.add(target) : _allowedTargets.remove(target);
        if (changed) emit TargetAllowed(target, allowed);
    }

    /// @inheritdoc ICuratedVault
    /// @dev Reverts rather than no-ops on a redundant call. An emergency control that silently does
    ///      nothing is worse than one that tells the operator the vault is already winding down.
    function pause() external onlyRole(GUARDIAN_ROLE) {
        if (_paused) revert AlreadyPaused();
        _paused = true;
        emit TradingPaused(msg.sender);
    }

    /// @inheritdoc ICuratedVault
    function unpause() external onlyRole(GUARDIAN_ROLE) {
        if (!_paused) revert NotPaused();
        _paused = false;
        emit TradingUnpaused(msg.sender);
    }

    // ─────────────────────────────────────────────────────────────────────
    // Exits — permissionless, and never pausable
    // ─────────────────────────────────────────────────────────────────────

    /// @inheritdoc ICuratedVault
    function redeemInKind(uint256 shares, address receiver, address owner)
        external
        nonReentrant
        returns (InKindPayout[] memory payouts)
    {
        if (receiver == address(0)) revert ZeroAddress();
        if (msg.sender != owner) _spendAllowance(owner, msg.sender, shares);

        // The same denominator `previewRedeem` uses, so this exit is never the more generous of the
        // two: paying `shares / (supply + 10^offset)` of each balance is worth exactly
        // `totalAssets * shares / (supply + 10^offset)`, one wei short of what `redeem` would quote.
        // Read before the burn — afterwards the denominator has already moved.
        uint256 denominator = totalSupply() + 10 ** _decimalsOffset();

        uint256 n = _valuedTokens.length;
        payouts = new InKindPayout[](n + 1);
        payouts[0] = InKindPayout({token: asset(), amount: _proRata(asset(), shares, denominator)});
        for (uint256 i; i < n; ++i) {
            address token = _valuedTokens[i];
            payouts[i + 1] = InKindPayout({token: token, amount: _proRata(token, shares, denominator)});
        }

        // Effects before interactions: the burn cannot be skipped by a token that reverts, and a
        // token that re-enters finds the shares already gone (and the guard closed regardless).
        _burn(owner, shares);

        for (uint256 i; i <= n; ++i) {
            uint256 amount = payouts[i].amount;
            // Zero transfers are legal but some tokens reject them, and an exit that reverts because
            // one position happened to be empty is exactly the failure this function exists to
            // remove. Reported in the payout either way.
            if (amount != 0) IERC20(payouts[i].token).safeTransfer(receiver, amount);
        }

        emit RedeemedInKind(msg.sender, receiver, owner, shares, payouts);
    }

    // ─────────────────────────────────────────────────────────────────────
    // Accounting
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Base-asset balance plus every registered non-base holding, priced via Chainlink.
    ///
    /// @dev Deliberately does **not** read Aqua virtual balances. Under Pattern 1 the tokens backing
    ///      an Aqua strategy are still held by this contract, so `balanceOf` already counts them —
    ///      adding the virtual balance on top would double-count and inflate share price.
    ///
    ///      A token with a zero balance is skipped before its feed is read. That matters: a feed
    ///      that goes stale or starts reporting garbage only blocks the vault while the vault
    ///      actually holds that token.
    function totalAssets() public view override returns (uint256 total) {
        total = IERC20(asset()).balanceOf(address(this));

        uint256 n = _valuedTokens.length;
        for (uint256 i; i < n; ++i) {
            address token = _valuedTokens[i];
            uint256 balance = IERC20(token).balanceOf(address(this));
            if (balance == 0) continue;

            Valuation memory v = _valuations[token];
            uint256 price = ChainlinkPriceLib.readPrice(IAggregatorV3(v.feed), _priceMaxAge);
            total += ChainlinkPriceLib.toAssetValue(balance, price, v.feedDecimals, v.tokenDecimals, _assetDecimals);
        }
    }

    /// @notice Virtual-share offset. 12 over a 6-decimal asset gives 18-decimal shares.
    ///
    /// @dev Two reasons. It is OpenZeppelin's defence against the classic first-depositor inflation
    ///      attack — a donation into an empty vault has to be 10^12 times larger to round a
    ///      subsequent depositor's shares to zero. And 18-decimal shares are what every wallet and
    ///      charting library expects.
    ///
    ///      Consequence callers must know: `convertToAssets(1e18)` returns a **6-decimal** number
    ///      (≈`1002506` for a share price of 1.0025), not an 18-decimal one.
    function _decimalsOffset() internal pure override returns (uint8) {
        return 12;
    }

    /// @dev Reentrancy guard on the ERC-4626 entry points. Without it, a venue call could re-enter
    ///      `deposit` midway through a rebalance — after the vault has spent USDC but before it
    ///      receives WETH — and mint shares against an understated `totalAssets()`.
    function _deposit(address caller, address receiver, uint256 assets, uint256 shares)
        internal
        override
        nonReentrant
    {
        super._deposit(caller, receiver, assets, shares);
    }

    /// @dev See `_deposit`. Same guard, same reason, opposite direction.
    function _withdraw(address caller, address receiver, address owner, uint256 assets, uint256 shares)
        internal
        override
        nonReentrant
    {
        super._withdraw(caller, receiver, owner, assets, shares);
    }

    // ─────────────────────────────────────────────────────────────────────
    // Frozen role graph
    // ─────────────────────────────────────────────────────────────────────

    /// @dev Unreachable anyway — `DEFAULT_ADMIN_ROLE` has no holder — but overridden so the
    ///      guarantee is legible to anyone reading the source rather than implied by an absence.
    function grantRole(bytes32, address) public pure override {
        revert RolesAreFrozen();
    }

    /// @dev See `grantRole`.
    function revokeRole(bytes32, address) public pure override {
        revert RolesAreFrozen();
    }

    /// @dev This one is *not* unreachable by default: AccessControl lets any holder renounce its own
    ///      role, which would let the agent brick its vault. Closed off explicitly.
    function renounceRole(bytes32, address) public pure override {
        revert RolesAreFrozen();
    }

    // ─────────────────────────────────────────────────────────────────────
    // Views
    // ─────────────────────────────────────────────────────────────────────

    /// @inheritdoc ICuratedVault
    function agent() external view returns (address) {
        return _agent;
    }

    /// @inheritdoc ICuratedVault
    function guardian() external view returns (address) {
        return _guardian;
    }

    /// @inheritdoc ICuratedVault
    function mandateHash() external view returns (bytes32) {
        return _mandateHash;
    }

    /// @inheritdoc ICuratedVault
    function priceMaxAge() external view returns (uint256) {
        return _priceMaxAge;
    }

    /// @inheritdoc ICuratedVault
    function paused() external view returns (bool) {
        return _paused;
    }

    /// @inheritdoc ICuratedVault
    function isAllowedTarget(address target) external view returns (bool) {
        return _allowedTargets.contains(target);
    }

    /// @inheritdoc ICuratedVault
    function allowedTargets() external view returns (address[] memory) {
        return _allowedTargets.values();
    }

    /// @inheritdoc ICuratedVault
    function valuedTokens() external view returns (address[] memory) {
        return _valuedTokens;
    }

    /// @inheritdoc ICuratedVault
    function priceFeed(address token) external view returns (address) {
        return _valuations[token].feed;
    }

    /// @inheritdoc ICuratedVault
    function holdings() external view returns (Holding[] memory out) {
        uint256 n = _valuedTokens.length;
        out = new Holding[](n + 1);

        address baseAsset = asset();
        uint256 baseBalance = IERC20(baseAsset).balanceOf(address(this));
        out[0] =
            Holding({token: baseAsset, decimals: _assetDecimals, balance: baseBalance, valueInAsset: baseBalance});

        for (uint256 i; i < n; ++i) {
            address token = _valuedTokens[i];
            Valuation memory v = _valuations[token];
            uint256 balance = IERC20(token).balanceOf(address(this));

            uint256 value;
            if (balance != 0) {
                uint256 price = ChainlinkPriceLib.readPrice(IAggregatorV3(v.feed), _priceMaxAge);
                value = ChainlinkPriceLib.toAssetValue(balance, price, v.feedDecimals, v.tokenDecimals, _assetDecimals);
            }

            out[i + 1] =
                Holding({token: token, decimals: v.tokenDecimals, balance: balance, valueInAsset: value});
        }
    }

    // ─────────────────────────────────────────────────────────────────────
    // Internals
    // ─────────────────────────────────────────────────────────────────────

    /// @dev Floor division, so the vault never pays out more than the redeemer's exact fraction and
    ///      the residue always favours the holders who stayed.
    function _proRata(address token, uint256 shares, uint256 denominator) private view returns (uint256) {
        return Math.mulDiv(IERC20(token).balanceOf(address(this)), shares, denominator);
    }

    /// @dev Every balance the direction rule judges — base asset at index 0, then the registered
    ///      holdings — or an **empty array when the vault is not paused**, which is how
    ///      `_requireMovedTowardBase` knows to skip the check. A paused vault always yields at least
    ///      one entry, so empty is unambiguous.
    function _bookIfPaused() private view returns (uint256[] memory book) {
        if (!_paused) return book;

        uint256 n = _valuedTokens.length;
        book = new uint256[](n + 1);
        book[0] = IERC20(asset()).balanceOf(address(this));
        for (uint256 i; i < n; ++i) {
            book[i + 1] = IERC20(_valuedTokens[i]).balanceOf(address(this));
        }
    }

    /// @dev The wind-down rule: cash may not fall and no holding may rise. Nothing else is checked —
    ///      in particular, not the price anything traded at. See `ICuratedVault.executeBatch`.
    ///
    ///      Registered tokens only. A token outside the valuation set is invisible here for the same
    ///      reason it is invisible to `totalAssets()`, and the mandate is what keeps the agent out of
    ///      them (`SECURITY.md`, *What is deliberately not defended*).
    function _requireMovedTowardBase(uint256[] memory before) private view {
        if (before.length == 0) return;

        uint256 baseAfter = IERC20(asset()).balanceOf(address(this));
        if (baseAfter < before[0]) revert WindDownWouldSpendBaseAsset(before[0], baseAfter);

        for (uint256 i; i < _valuedTokens.length; ++i) {
            address token = _valuedTokens[i];
            uint256 balanceAfter = IERC20(token).balanceOf(address(this));
            if (balanceAfter > before[i + 1]) {
                revert WindDownWouldIncreaseHolding(token, before[i + 1], balanceAfter);
            }
        }
    }

    /// @dev `decimals()` is optional in ERC-20. Falling back to 18 matches OpenZeppelin's own
    ///      convention in `ERC4626`.
    function _tryDecimals(address token) private view returns (uint8) {
        try IERC20Metadata(token).decimals() returns (uint8 d) {
            return d;
        } catch {
            return 18;
        }
    }

    /// @dev First four bytes of `data`, or zero for calldata too short to carry a selector.
    function _selectorOf(bytes memory data) private pure returns (bytes4 selector) {
        if (data.length < 4) return bytes4(0);
        assembly {
            selector := mload(add(data, 0x20))
        }
    }
}
