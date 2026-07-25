// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {StdInvariant} from "forge-std/StdInvariant.sol";
import {Test} from "forge-std/Test.sol";

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import {CuratedVault} from "../../src/CuratedVault.sol";
import {VaultFactory} from "../../src/VaultFactory.sol";
import {ICuratedVault} from "../../src/interfaces/ICuratedVault.sol";
import {IVaultFactory} from "../../src/interfaces/IVaultFactory.sol";
import {ChainlinkPriceLib} from "../../src/libraries/ChainlinkPriceLib.sol";
import {IAggregatorV3} from "../../src/interfaces/IAggregatorV3.sol";
import {MockAggregatorV3} from "../mocks/MockAggregatorV3.sol";
import {MockERC20} from "../mocks/MockERC20.sol";
import {SwapVenue} from "../mocks/SwapVenue.sol";
import {VaultHandler} from "./VaultHandler.sol";

/// @notice Properties that must hold after *any* sequence of deposits, withdrawals, agent
///         rebalances, price moves and attacks.
///
/// @dev Unit tests check the cases we thought of. These check the ones we did not: the fuzzer picks
///      the order, the actors and the amounts, and each invariant is re-checked after every call.
///      Every one below is phrased as a claim a reader can evaluate without reading the vault.
contract VaultInvariantsTest is StdInvariant, Test {
    MockERC20 internal usdc;
    MockERC20 internal weth;
    MockAggregatorV3 internal feed;
    SwapVenue internal venue;
    VaultFactory internal factory;
    CuratedVault internal vault;
    VaultHandler internal handler;

    address internal platform = makeAddr("platform");
    address internal agent = makeAddr("agent");
    address internal guardian = makeAddr("guardian");

    int256 internal constant ETH_USD = 3000e8;

    function setUp() public {
        vm.warp(1_700_000_000);

        usdc = new MockERC20("USD Coin", "USDC", 6);
        weth = new MockERC20("Wrapped Ether", "WETH", 18);
        feed = new MockAggregatorV3(8, "ETH / USD", ETH_USD);
        venue = new SwapVenue(usdc, weth, IAggregatorV3(address(feed)));

        // Deep inventory so the venue can always fill; it is a price oracle with a balance sheet,
        // not a market being modelled.
        usdc.mint(address(venue), 1_000_000_000e6);
        weth.mint(address(venue), 1_000_000e18);

        address[] memory targets = new address[](3);
        targets[0] = address(venue);
        targets[1] = address(usdc);
        targets[2] = address(weth);

        ICuratedVault.TokenValuation[] memory valuations = new ICuratedVault.TokenValuation[](1);
        valuations[0] = ICuratedVault.TokenValuation({token: address(weth), feed: address(feed)});

        // priceMaxAge 0: the fuzzer warps time freely, and a staleness revert would abort sequences
        // for a reason that says nothing about the properties under test. Staleness has its own
        // dedicated unit tests.
        factory = new VaultFactory(platform, targets, valuations, 0);
        vault = CuratedVault(
            factory.createVault(
                IVaultFactory.CreateParams({
                    asset: address(usdc),
                    name: "Curated USDC",
                    symbol: "cUSDC",
                    agent: agent,
                    guardian: guardian,
                    mandateHash: keccak256("invariant-mandate")
                })
            )
        );

        address[] memory actors = new address[](4);
        actors[0] = makeAddr("alice");
        actors[1] = makeAddr("bob");
        actors[2] = makeAddr("carol");
        actors[3] = agent; // the agent is also a depositor, so privilege is genuinely mixed in

        handler = new VaultHandler(vault, usdc, weth, feed, venue, agent, guardian, actors);

        targetContract(address(handler));
    }

    // ─────────────────────────────────────────────────────────────────────
    // 1. Only AGENT_ROLE can move value
    // ─────────────────────────────────────────────────────────────────────

    /// @dev Includes the guardian, which is the case that matters: it controls the allowlist, so if
    ///      it could also spend, widening the list would become a route to the money rather than a
    ///      blast-radius control.
    function invariant_onlyTheAgentCanMoveValue() public view {
        assertEq(handler.unauthorizedValueMoves(), 0, "a non-agent moved value");
    }

    // ─────────────────────────────────────────────────────────────────────
    // 2. execute can never reach a non-allowlisted target
    // ─────────────────────────────────────────────────────────────────────

    /// @dev Tried with arbitrary calldata and via `executeBatch`, where a legitimate first step
    ///      might otherwise launder an illegitimate second one.
    function invariant_agentCannotReachANonAllowlistedTarget() public view {
        assertEq(handler.nonAllowlistedTargetsReached(), 0, "reached a target off the allowlist");
    }

    // ─────────────────────────────────────────────────────────────────────
    // 3. The role graph is frozen at genesis
    // ─────────────────────────────────────────────────────────────────────

    function invariant_roleGraphIsFrozen() public view {
        assertEq(handler.roleChangesAccepted(), 0, "a role change was accepted");
        assertEq(handler.reinitializations(), 0, "the vault was re-initialized");

        assertEq(vault.agent(), agent, "agent replaced");
        assertEq(vault.guardian(), guardian, "guardian replaced");
        assertTrue(vault.hasRole(vault.AGENT_ROLE(), agent), "agent lost its role");
        assertFalse(vault.hasRole(0x00, platform), "an admin appeared");
        assertFalse(vault.hasRole(0x00, agent), "an admin appeared");
    }

    // ─────────────────────────────────────────────────────────────────────
    // 4. totalAssets() is exactly the valued holdings
    // ─────────────────────────────────────────────────────────────────────

    /// @dev Recomputed independently here from balances and the live feed, so this catches a
    ///      valuation bug rather than restating one.
    function invariant_totalAssetsEqualsValuedHoldings() public view {
        uint256 expected = usdc.balanceOf(address(vault));

        uint256 wethBalance = weth.balanceOf(address(vault));
        if (wethBalance != 0) {
            (, int256 answer,,,) = feed.latestRoundData();
            // The handler bounds the feed to a strictly positive range, so the cast is safe.
            // forge-lint: disable-next-line(unsafe-typecast)
            expected += ChainlinkPriceLib.toAssetValue(wethBalance, uint256(answer), 8, 18, 6);
        }

        assertEq(vault.totalAssets(), expected, "totalAssets diverged from the holdings");
    }

    /// @dev The same claim from the other side: `holdings()` is what the harness and the dApp render,
    ///      so it must sum to the number the contract prices shares with. If these ever disagree the
    ///      UI is lying about the portfolio.
    function invariant_holdingsSumToTotalAssets() public view {
        ICuratedVault.Holding[] memory h = vault.holdings();
        uint256 sum;
        for (uint256 i; i < h.length; ++i) {
            sum += h[i].valueInAsset;
        }
        assertEq(sum, vault.totalAssets(), "holdings() does not sum to totalAssets()");
    }

    // ─────────────────────────────────────────────────────────────────────
    // 5. Plain deposits and withdrawals do not move the share price
    // ─────────────────────────────────────────────────────────────────────

    /// @dev Stated as a direction rather than a magnitude, deliberately. Only an agent action or a
    ///      price move may raise or lower what a share is worth on purpose; entering and leaving may
    ///      round the price *up* — that is ERC-4626 rounding in the vault's favour and it leaves the
    ///      remaining holders better off — but must never round it *down*, because that is value
    ///      moving from the holders who stayed to the actor who came or went.
    function invariant_entryAndExitNeverExtractValue() public view {
        assertEq(handler.sharePriceMovedByPlainFlow(), 0, "a deposit or withdrawal lowered the share price");
    }

    // ─────────────────────────────────────────────────────────────────────
    // 6. The vault can honour every holder
    // ─────────────────────────────────────────────────────────────────────

    /// @dev Solvency. If the sum of what everyone could redeem ever exceeded what the vault holds,
    ///      the last holder out would eat the shortfall — which is exactly what a donation-inflation
    ///      attack tries to engineer.
    function invariant_vaultIsSolvent() public view {
        uint256 owed;
        uint256 n = handler.actorCount();
        for (uint256 i; i < n; ++i) {
            uint256 shares = vault.balanceOf(handler.actorAt(i));
            if (shares != 0) owed += vault.previewRedeem(shares);
        }
        assertLe(owed, vault.totalAssets(), "holders are owed more than the vault holds");
    }

    /// @dev The supply-side statement of the same property.
    function invariant_supplyAndAssetsAgreeOnEmptiness() public view {
        if (vault.totalSupply() == 0) {
            // An empty vault may still hold donated assets — they simply belong to the next
            // depositor. What must never happen is shares outstanding against nothing.
            return;
        }
        assertGt(vault.totalAssets(), 0, "shares exist against an empty vault");
    }

    // ─────────────────────────────────────────────────────────────────────
    // 7. Configuration set at genesis stays set
    // ─────────────────────────────────────────────────────────────────────

    /// @dev The valuation set has no setter for anyone, deliberately: a mutable price feed is the
    ///      one control that would let its holder reprice every share at will.
    function invariant_valuationSetIsImmutable() public view {
        assertEq(vault.valuedTokens().length, 1, "valuation set changed size");
        assertEq(vault.priceFeed(address(weth)), address(feed), "the WETH feed was swapped");
        assertEq(vault.asset(), address(usdc), "the base asset changed");
        assertEq(vault.mandateHash(), keccak256("invariant-mandate"), "the mandate hash changed");
    }

    // ─────────────────────────────────────────────────────────────────────
    // A note on coverage — the failure mode these invariants cannot self-detect
    // ─────────────────────────────────────────────────────────────────────
    //
    // Every property above holds trivially on a vault nothing ever happened to, so a handler action
    // that silently became a no-op would turn this whole file green while proving nothing.
    //
    // The obvious guard — asserting in `afterInvariant()` that the campaign deposited, withdrew and
    // rebalanced — was tried and removed. Foundry evaluates that hook per sequence, and a 32-call
    // sequence drawn from twelve handler functions legitimately will not always contain a deposit,
    // so it failed on sequence composition rather than on anything about the vault.
    //
    // `HandlerSanity.t.sol` is the guarantee instead, and it is the stronger one: it drives each
    // action deterministically and asserts each *individually*, so a broken action fails with its
    // own name rather than as an aggregate. Foundry also prints a per-function call distribution at
    // the end of a run — a zero in the `calls` column there is the same signal, for free.

}
