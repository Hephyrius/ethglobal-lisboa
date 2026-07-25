// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import {CuratedVault} from "../../src/CuratedVault.sol";
import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";
import {MockAggregatorV3} from "../mocks/MockAggregatorV3.sol";
import {MockERC20} from "../mocks/MockERC20.sol";
import {SwapVenue} from "../mocks/SwapVenue.sol";

/// @notice Drives the vault the way an adversary would, and records what got through.
///
/// @dev The handler pattern, and why it is worth the extra file: unguided fuzzing of a vault spends
///      almost every run reverting on `transferFrom` before it reaches any interesting state. A
///      handler bounds the inputs so sequences are *reachable*, while still letting the fuzzer pick
///      the order, the actor and the amounts.
///
///      **The counters are the point.** Rather than asserting inside each action — which would stop
///      the sequence at the first surprise and hide everything after it — every attack that *should*
///      fail increments a ghost counter when it succeeds. The invariant then asserts the counter is
///      still zero, so one violation anywhere in a 32-call sequence is caught and reported with the
///      full call history that produced it.
contract VaultHandler is Test {
    CuratedVault public immutable vault;
    MockERC20 public immutable usdc;
    MockERC20 public immutable weth;
    MockAggregatorV3 public immutable feed;
    SwapVenue public immutable venue;

    address public immutable agent;
    address public immutable guardian;

    address[] internal actors;
    address internal currentActor;

    /// @dev Sentinel for "this vault has no shares outstanding, so there is no price per share".
    uint256 internal constant SHARE_PRICE_UNDEFINED = 0;

    /// @dev One unit of the base asset — 0.000001 USDC — per in-kind exit, and it is not slop.
    ///
    ///      `redeemInKind` hands over a floored fraction of each raw *balance*. The vault's books are
    ///      kept in the base asset, and converting a WETH balance into that number floors too. Those
    ///      two floors do not commute: `value(w − ⌊w·f⌋)` can exceed `value(w)·(1 − f)` by up to one
    ///      unit, so the redeemer can leave with one unit more than their exact quote.
    ///
    ///      Closing it would mean valuing the payout — reading the oracle — which is the one thing
    ///      this exit must not do, because being oracle-free is what makes it unconditional. So the
    ///      trade is stated rather than hidden: **an exit that reads no oracle cannot also be
    ///      oracle-exact.** Generalises to one unit per valued token; the invariant fixture has one.
    uint256 internal constant VALUATION_FLOOR_SLACK = 1;

    // ── ghosts: every one of these must still be zero at the end ─────────

    /// @notice `execute`/`executeBatch`/`approveVenue` succeeded for a caller without `AGENT_ROLE`.
    uint256 public unauthorizedValueMoves;
    /// @notice The agent reached a target that was not on the allowlist.
    uint256 public nonAllowlistedTargetsReached;
    /// @notice Any role grant, revoke or renounce succeeded.
    uint256 public roleChangesAccepted;
    /// @notice A plain deposit or withdrawal moved the share price *down* — i.e. the actor entering
    ///         or leaving extracted value from the holders who stayed.
    uint256 public sharePriceMovedByPlainFlow;
    /// @notice `initialize` succeeded a second time.
    uint256 public reinitializations;
    /// @notice An agent call that landed *while paused* left the book further from cash — measured
    ///         from the balances afterwards, not inferred from whether the vault reverted.
    uint256 public windDownWentTheWrongWay;
    /// @notice A holder was refused an in-kind exit on their own shares. The exit is unconditional,
    ///         so any non-zero value here means it is not.
    uint256 public inKindExitsRefused;
    /// @notice An in-kind exit removed more value from the vault than the redeemer's shares were
    ///         quoted at. See `VALUATION_FLOOR_SLACK` for the one unit of tolerance and why it is
    ///         one unit rather than zero.
    uint256 public inKindTookMoreThanQuoted;

    // ── ghosts: bookkeeping ──────────────────────────────────────────────

    uint256 public totalDeposited;
    uint256 public totalWithdrawn;
    uint256 public depositCount;
    uint256 public withdrawCount;
    uint256 public agentSwapCount;
    uint256 public pauseToggles;
    uint256 public inKindExits;
    /// @notice Agent calls that landed while the vault was paused. If this stays zero the wind-down
    ///         invariant is vacuous, which is the failure mode a ghost counter cannot see by itself.
    uint256 public agentCallsWhilePaused;

    constructor(
        CuratedVault vault_,
        MockERC20 usdc_,
        MockERC20 weth_,
        MockAggregatorV3 feed_,
        SwapVenue venue_,
        address agent_,
        address guardian_,
        address[] memory actors_
    ) {
        vault = vault_;
        usdc = usdc_;
        weth = weth_;
        feed = feed_;
        venue = venue_;
        agent = agent_;
        guardian = guardian_;
        actors = actors_;
    }

    modifier useActor(uint256 seed) {
        currentActor = actors[bound(seed, 0, actors.length - 1)];
        vm.startPrank(currentActor);
        _;
        vm.stopPrank();
    }

    // ─────────────────────────────────────────────────────────────────────
    // Honest flow
    // ─────────────────────────────────────────────────────────────────────

    /// @dev Share price is sampled either side. A deposit must not move it: that is what stops an
    ///      entrant minting themselves value out of the existing holders.
    function deposit(uint256 assets, uint256 actorSeed) external useActor(actorSeed) {
        assets = bound(assets, 1e6, 1_000_000e6);

        uint256 priceBefore = _sharePrice();
        usdc.mint(currentActor, assets);
        usdc.approve(address(vault), assets);
        try vault.deposit(assets, currentActor) {
            totalDeposited += assets;
            depositCount++;
            _recordSharePriceDrift(priceBefore);
        } catch {}
    }

    /// @dev Falls back to *any* holder when the drawn actor has no shares. Without that, a redeem
    ///      only fires when the fuzzer happens to draw the same actor twice, so most withdrawal
    ///      calls were silently no-ops and whole sequences never exercised the exit path at all —
    ///      caught by `afterInvariant`, which is exactly what that hook is for.
    function redeem(uint256 sharesSeed, uint256 actorSeed) external useActor(actorSeed) {
        if (vault.balanceOf(currentActor) == 0) {
            address holder = _anyHolder();
            if (holder == address(0)) return;
            vm.stopPrank();
            currentActor = holder;
            vm.startPrank(currentActor);
        }

        uint256 held = vault.balanceOf(currentActor);
        if (held == 0) return;
        uint256 shares = bound(sharesSeed, 1, held);

        uint256 priceBefore = _sharePrice();
        try vault.redeem(shares, currentActor, currentActor) returns (uint256 assets) {
            totalWithdrawn += assets;
            withdrawCount++;
            _recordSharePriceDrift(priceBefore);
        } catch {}
    }

    /// @notice The real rebalance path: approve, then swap, as one atomic `executeBatch`.
    /// @dev While the vault is paused this direction is a purchase, so every one of these should be
    ///      refused. It is left in the rotation rather than skipped precisely so the fuzzer keeps
    ///      trying it — an attack that is never attempted is never disproved.
    function agentSwapUsdcForWeth(uint256 amount) external {
        uint256 available = usdc.balanceOf(address(vault));
        if (available < 2e6) return;
        amount = bound(amount, 1e6, available);

        ICuratedVault.Call[] memory calls = new ICuratedVault.Call[](2);
        calls[0] = ICuratedVault.Call({
            target: address(usdc),
            value: 0,
            data: abi.encodeCall(IERC20.approve, (address(venue), amount))
        });
        calls[1] = ICuratedVault.Call({
            target: address(venue),
            value: 0,
            data: abi.encodeCall(SwapVenue.swapUsdcForWeth, (amount))
        });

        _agentBatch(calls);
    }

    function agentSwapWethForUsdc(uint256 amount) external {
        uint256 available = weth.balanceOf(address(vault));
        if (available < 1e12) return;
        amount = bound(amount, 1e12, available);

        ICuratedVault.Call[] memory calls = new ICuratedVault.Call[](2);
        calls[0] = ICuratedVault.Call({
            target: address(weth),
            value: 0,
            data: abi.encodeCall(IERC20.approve, (address(venue), amount))
        });
        calls[1] = ICuratedVault.Call({
            target: address(venue),
            value: 0,
            data: abi.encodeCall(SwapVenue.swapWethForUsdc, (amount))
        });

        _agentBatch(calls);
    }

    /// @notice The guardian flipping wind-down on and off at moments of the fuzzer's choosing.
    /// @dev Weighted toward pausing (two in three) so campaigns spend real time in the state the new
    ///      rule governs. An even split leaves the paused window too short for a rebalance to land
    ///      inside it, and a rule nothing is ever tested against passes for free.
    function guardianTogglesPause(uint256 seed) external {
        bool wantPaused = bound(seed, 0, 2) != 0;
        if (wantPaused == vault.paused()) return;

        vm.prank(guardian);
        if (wantPaused) vault.pause();
        else vault.unpause();
        pauseToggles++;
    }

    /// @notice The exit that has no precondition beyond holding shares. Every refusal is a bug.
    /// @dev Same any-holder fallback as `redeem`, for the same reason: without it the action is a
    ///      silent no-op on most draws and the invariant proves nothing.
    function redeemInKind(uint256 sharesSeed, uint256 actorSeed) external useActor(actorSeed) {
        if (vault.balanceOf(currentActor) == 0) {
            address holder = _anyHolder();
            if (holder == address(0)) return;
            vm.stopPrank();
            currentActor = holder;
            vm.startPrank(currentActor);
        }

        uint256 held = vault.balanceOf(currentActor);
        if (held == 0) return;
        uint256 shares = bound(sharesSeed, 1, held);

        // Checked against its own quote rather than against the share price, and the difference is a
        // finding rather than a convenience. `convertToAssets(1e18)` divides by `totalSupply + 10¹²`,
        // so when supply is small — a donation into an empty vault, then a one-USDC deposit, which
        // the fuzzer reaches — that denominator is ~10¹² and a *single unit* of valuation rounding
        // shows up as ~10⁶ in the read-out. `deposit` and `redeem` never tripped it only because they
        // move the base asset, whose valuation is exact; this is the first action to move a *priced*
        // holding. The share-price check is a proxy whose resolution depends on supply, so for this
        // action the exact property is asserted instead: value out must not exceed value quoted.
        uint256 quoted = vault.previewRedeem(shares);
        uint256 assetsBefore = vault.totalAssets();

        try vault.redeemInKind(shares, currentActor, currentActor) {
            inKindExits++;
            // Balances only fall here, and the valuation is monotone, so this cannot underflow.
            uint256 removed = assetsBefore - vault.totalAssets();
            if (removed > quoted + VALUATION_FLOOR_SLACK) inKindTookMoreThanQuoted++;
        } catch {
            inKindExitsRefused++;
        }
    }

    /// @notice Move the oracle. Bounded to a plausible range so prices stay meaningful.
    function movePrice(uint256 newPrice) external {
        feed.setAnswer(int256(bound(newPrice, 100e8, 100_000e8)));
    }

    // ─────────────────────────────────────────────────────────────────────
    // Attacks — each must fail; a success bumps a counter
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Anyone who is not the agent trying to move value, with arbitrary calldata.
    function attackUnauthorizedExecute(uint256 callerSeed, uint256 targetSeed, bytes calldata data) external {
        address caller = actors[bound(callerSeed, 0, actors.length - 1)];
        if (caller == agent) return;
        address target = _someAllowlistedTarget(targetSeed);

        vm.prank(caller);
        try vault.execute(target, 0, data) {
            unauthorizedValueMoves++;
        } catch {}

        vm.prank(caller);
        try vault.approveVenue(address(usdc), address(venue), type(uint256).max) {
            unauthorizedValueMoves++;
        } catch {}
    }

    /// @notice The guardian is the interesting caller here: it controls the allowlist, so if any
    ///         path let it spend, widening the list would become a way to reach the money.
    function attackGuardianSpends(bytes calldata data) external {
        vm.prank(guardian);
        try vault.execute(address(usdc), 0, data) {
            unauthorizedValueMoves++;
        } catch {}
    }

    /// @notice The agent aiming at an address that is not allowlisted, including via a batch whose
    ///         first step is legitimate — ordering must not launder a bad target.
    function attackNonAllowlistedTarget(address target, bytes calldata data) external {
        if (vault.isAllowedTarget(target)) return;
        if (target == address(0)) return;

        vm.prank(agent);
        try vault.execute(target, 0, data) {
            nonAllowlistedTargetsReached++;
        } catch {}

        ICuratedVault.Call[] memory calls = new ICuratedVault.Call[](2);
        calls[0] = ICuratedVault.Call({
            target: address(usdc),
            value: 0,
            data: abi.encodeCall(IERC20.approve, (address(venue), 1))
        });
        calls[1] = ICuratedVault.Call({target: target, value: 0, data: data});

        vm.prank(agent);
        try vault.executeBatch(calls) {
            nonAllowlistedTargetsReached++;
        } catch {}
    }

    /// @notice Every way AccessControl normally lets a role graph change.
    function attackRoleChange(uint256 callerSeed) external {
        address caller = actors[bound(callerSeed, 0, actors.length - 1)];
        bytes32 agentRole = vault.AGENT_ROLE();

        vm.startPrank(caller);
        try vault.grantRole(agentRole, caller) {
            roleChangesAccepted++;
        } catch {}
        try vault.revokeRole(agentRole, agent) {
            roleChangesAccepted++;
        } catch {}
        try vault.renounceRole(agentRole, caller) {
            roleChangesAccepted++;
        } catch {}
        vm.stopPrank();

        // The agent renouncing its own role is the one AccessControl allows by default, and it
        // would brick the vault it curates.
        vm.prank(agent);
        try vault.renounceRole(agentRole, agent) {
            roleChangesAccepted++;
        } catch {}
    }

    /// @notice Re-initialisation, which would rewrite the agent, the allowlist and the valuation set.
    function attackReinitialize(address newAgent) external {
        ICuratedVault.InitParams memory p = ICuratedVault.InitParams({
            asset: address(usdc),
            name: "Hijacked",
            symbol: "HAX",
            agent: newAgent,
            guardian: newAgent,
            mandateHash: bytes32(0),
            allowedTargets: new address[](0),
            valuations: new ICuratedVault.TokenValuation[](0),
            priceMaxAge: 0
        });

        try vault.initialize(p) {
            reinitializations++;
        } catch {}
    }

    /// @notice A direct token donation. Must not mint shares, and must not let the donor extract
    ///         more than they put in — the classic 4626 inflation setup.
    function attackDonate(uint256 amount, uint256 actorSeed) external useActor(actorSeed) {
        amount = bound(amount, 1, 100_000e6);
        usdc.mint(currentActor, amount);
        // Unchecked deliberately: a raw donation that bypasses deposit() is the attack.
        // forge-lint: disable-next-line(erc20-unchecked-transfer)
        usdc.transfer(address(vault), amount);
    }

    // ─────────────────────────────────────────────────────────────────────
    // Views used by the invariants
    // ─────────────────────────────────────────────────────────────────────

    function actorCount() external view returns (uint256) {
        return actors.length;
    }

    function actorAt(uint256 i) external view returns (address) {
        return actors[i];
    }

    /// @dev `0` means **undefined**, not "worthless". A vault with no shares outstanding has no
    ///      price per share, and conflating the two is what made an ordinary full exit look like a
    ///      collapse — see `_recordSharePriceDrift`.
    function _sharePrice() private view returns (uint256) {
        if (vault.totalSupply() == 0) return SHARE_PRICE_UNDEFINED;
        return vault.convertToAssets(1e18);
    }

    /// @dev **Direction, not magnitude — and that distinction is the whole property.**
    ///
    ///      An upward move is ERC-4626 rounding in the vault's favour: the actor entering or leaving
    ///      rounded against themselves and the remaining holders are marginally better off. That is
    ///      correct, and after a donation into a near-empty vault it can be much larger than one
    ///      unit while still being entirely benign. An earlier version of this checked `|delta| > 1`
    ///      and failed on exactly that case — a real finding about the *test*, not the vault.
    ///
    ///      A downward move is the one that matters: it means the actor extracted value from the
    ///      holders who stayed, which is precisely what a donation-inflation attack engineers. One
    ///      unit of tolerance covers the floor division in the price read-out itself.
    ///      Both ends must be defined for the comparison to mean anything: the first deposit into an
    ///      empty vault *establishes* the price rather than moving it, and a full exit leaves no
    ///      shares to price. Treating the latter as a drop to zero flagged an ordinary complete
    ///      withdrawal as value extraction — the third and last measurement bug this check went
    ///      through, all of the same shape: asserting something stronger than the property.
    function _recordSharePriceDrift(uint256 priceBefore) private {
        uint256 priceAfter = _sharePrice();
        if (priceBefore == SHARE_PRICE_UNDEFINED || priceAfter == SHARE_PRICE_UNDEFINED) return;
        if (priceAfter + 1 < priceBefore) sharePriceMovedByPlainFlow++;
    }

    /// @dev Runs an agent batch and, when the vault is paused, re-derives the wind-down rule from
    ///      the balances rather than trusting the vault's own verdict. If the contract's check were
    ///      subtly wrong — measuring the wrong token, or the wrong end of the batch — trusting its
    ///      revert would make this invariant a restatement of the bug.
    function _agentBatch(ICuratedVault.Call[] memory calls) private {
        bool wasPaused = vault.paused();
        uint256 usdcBefore = usdc.balanceOf(address(vault));
        uint256 wethBefore = weth.balanceOf(address(vault));

        vm.prank(agent);
        try vault.executeBatch(calls) {
            agentSwapCount++;
            if (!wasPaused) return;

            agentCallsWhilePaused++;
            if (usdc.balanceOf(address(vault)) < usdcBefore) windDownWentTheWrongWay++;
            if (weth.balanceOf(address(vault)) > wethBefore) windDownWentTheWrongWay++;
        } catch {}
    }

    function _someAllowlistedTarget(uint256 seed) private view returns (address) {
        address[] memory targets = vault.allowedTargets();
        return targets[bound(seed, 0, targets.length - 1)];
    }

    /// @dev First actor holding any shares, or the zero address if the vault has no holders yet.
    function _anyHolder() private view returns (address) {
        for (uint256 i; i < actors.length; ++i) {
            if (vault.balanceOf(actors[i]) != 0) return actors[i];
        }
        return address(0);
    }
}
