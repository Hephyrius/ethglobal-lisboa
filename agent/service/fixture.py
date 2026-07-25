"""Fixture-mode services — the harness with the network unplugged.

These exist so Lane E is never blocked (master plan §14) and so the whole lane
stays testable with no Ollama, no RPC and no other lane present. They are the
default: `AGENT_MODE=fixture`.

Two deliberate choices about *what* fixture mode serves:

**The decision feed covers every status, not four copies of the happy path.**
`AgentAction.status` has five values and Lane E has to render all of them. If
fixture mode only ever returned `executed`, the `rejected` and `failed` states
would first appear during the live demo, which is the worst possible time to
discover the UI has no design for them. The seeded feed therefore includes a
hold, a validation rejection and an on-chain failure alongside the successful
rebalance.

**Timestamps are relative to now, not the fixture's fixed date.** A feed frozen
at 2026-07-25T14:05Z reads as broken at any other hour. These count backwards
from the current time so the dApp always shows a plausible recent history.

Values otherwise come straight from `packages/schema/fixtures/`, so what Lane E
renders here is exactly the shape live mode produces.
"""

from __future__ import annotations

from datetime import timedelta

from curator_schema import (
    AgentAction,
    AllocationDecision,
    Mandate,
    ModelProvenance,
    VaultPerformance,
    VaultState,
)

from .. import fixtures
from ..api.schemas import (
    ChatMessage,
    GenesisChatResponse,
    GenesisFinalizeResponse,
    MandateDraft,
)
from ..clock import utcnow
from ..config import Settings
from ..mandate.hashing import mandate_hash
from ..performance import summarize
from ..performance.fixture_curve import fixture_curve
from ..performance.window import window_points

__all__ = ["FixtureVaultService", "FixtureGenesisService"]

#: Deterministic stand-ins. Recognisably fake, valid `Address` / `Bytes32`.
_FIXTURE_VAULT = "0x1111111111111111111111111111111111111111"
_FIXTURE_DEPLOY_TX = "0x" + "de" * 32


class FixtureVaultService:
    """`VaultService` over the golden fixtures."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def state(self, vault: str) -> VaultState:
        # Echo back the address that was asked for. Serving the fixture's own
        # address would make the dApp render a different vault than the one in
        # the URL, which looks like a bug and hides real ones.
        return fixtures.vault_state().model_copy(update={"address": vault})

    async def mandate(self, vault: str) -> Mandate:
        return fixtures.mandate()

    async def tick(self, vault: str) -> AgentAction:
        """A fresh successful cycle, timestamped now."""
        return self._executed(vault, age=timedelta(0), index=0)

    async def performance(self, vault: str, window: str = "all") -> VaultPerformance:
        """A synthetic curve, so Lane E can build the chart before real history
        exists.

        Deliberately a *gentle* curve with one real drawdown rather than a
        straight line up: a chart component developed against a monotonic series
        never gets its axis, its negative-return colour or its drawdown marker
        exercised, and all three appear for the first time in front of a judge.

        Deterministic — no clock beyond `utcnow()`, no randomness — so a
        screenshot taken twice looks the same.
        """
        points = fixture_curve(vault)
        points = window_points(points, window)
        return VaultPerformance(vault=vault, points=points, summary=summarize(vault, points))

    async def decisions(self, vault: str, limit: int) -> list[AgentAction]:
        feed = [
            self._executed(vault, age=timedelta(minutes=4), index=1),
            self._held(vault, age=timedelta(minutes=64), index=2),
            self._rejected(vault, age=timedelta(minutes=124), index=3),
            self._failed(vault, age=timedelta(minutes=184), index=4),
        ]
        return feed[:limit]

    # ── the four statuses ─────────────────────────────────────────────────

    def _base(self, vault: str, age: timedelta, index: int) -> dict:
        return {
            "id": f"act_fixture_{index:04d}",
            "vault": vault,
            "timestamp": utcnow() - age,
            "mandate_version_before": 1,
            "mandate_version_after": 1,
        }

    def _model(self, retries: int = 0) -> ModelProvenance:
        return ModelProvenance(
            backend=self._settings.model_backend,
            name=self._settings.model_name,
            validation_retries=retries,
        )

    def _executed(self, vault: str, age: timedelta, index: int) -> AgentAction:
        golden = fixtures.agent_action()
        return AgentAction(
            **self._base(vault, age, index),
            status="executed",
            # Attached deliberately: Lane E's decision feed has to show data
            # consulted (with provenance) -> reasoning -> tx hash, and it cannot
            # build that view if the snapshot never crosses the wire.
            snapshot=fixtures.market_snapshot(),
            decision=golden.decision,
            plan=golden.plan,
            tx_hashes=golden.tx_hashes,
            model=self._model(retries=1),
            duration_ms=8420,
        )

    def _held(self, vault: str, age: timedelta, index: int) -> AgentAction:
        return AgentAction(
            **self._base(vault, age, index),
            status="held",
            snapshot=fixtures.market_snapshot(),
            decision=AllocationDecision(
                action="hold",
                reasoning=(
                    "Morpho Blue USDC at 5.87% still leads Aave v3 at 4.32%, but the gap has "
                    "not moved since the last tick and the position is already sized to the "
                    "mandate's 60% ceiling. Rebalancing now would pay slippage to end up where "
                    "the vault already is. Holding is the cheaper expression of the same view."
                ),
                facts_used=["f1", "f2", "f4"],
                confidence=0.74,
            ),
            model=self._model(),
            duration_ms=5110,
        )

    def _rejected(self, vault: str, age: timedelta, index: int) -> AgentAction:
        """Output validation caught the model and nothing reached the chain.

        Kept and rendered, per `packages/schema/README.md`: these records are
        the evidence that the validation layer is load-bearing.
        """
        return AgentAction(
            **self._base(vault, age, index),
            status="rejected",
            snapshot=fixtures.market_snapshot(),
            model=self._model(retries=3),
            error=(
                "decision rejected after 3 attempts: target_allocations named asset 'cbETH', "
                "which is not in the mandate's allowed_assets ['USDC', 'WETH']; final attempt "
                "also cited fact id 'f9', which was not in the snapshot"
            ),
            duration_ms=21870,
        )

    def _failed(self, vault: str, age: timedelta, index: int) -> AgentAction:
        golden = fixtures.agent_action()
        return AgentAction(
            **self._base(vault, age, index),
            status="failed",
            snapshot=fixtures.market_snapshot(),
            decision=golden.decision,
            plan=golden.plan,
            model=self._model(),
            error="step 2 reverted: UniversalRouter V3TooLittleReceived (quote went stale)",
            duration_ms=12030,
        )


class FixtureGenesisService:
    """`GenesisService` with a scripted conversation.

    The reply is canned but the *draft grows with the conversation*, because a
    static draft would let the genesis UI ship without handling the case it
    actually has to handle: fields arriving progressively across turns.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def available_sources(self) -> list[str]:
        return list(fixtures.mandate().permitted_data_sources)

    def available_venues(self) -> list[str]:
        return list(fixtures.mandate().permitted_venues)

    async def chat(self, messages: list[ChatMessage]) -> GenesisChatResponse:
        golden = fixtures.mandate()
        turns = sum(1 for m in messages if m.role == "user")

        # Reveal the mandate in the order a real conversation would settle it:
        # what it is for, then what it may hold, then what it may consult.
        draft = MandateDraft(version=1, base_asset=golden.base_asset)
        if turns >= 1:
            draft.name = golden.name
            draft.objective = golden.objective
        if turns >= 2:
            draft.risk_posture = golden.risk_posture
            draft.constraints = golden.constraints
        if turns >= 3:
            draft.permitted_data_sources = list(golden.permitted_data_sources)
            draft.permitted_venues = list(golden.permitted_venues)
            draft.update_rules = golden.update_rules

        replies = [
            "Understood — a USDC vault that prioritises capital preservation over headline "
            "APY. I have set the base asset to USDC. What should it be allowed to hold "
            "besides USDC, and how much drawdown is acceptable?",
            "Noted: WETH allowed, conservative posture, and at least 20% held in cash so "
            "redemptions never force an unwind. I have capped any single position at 60% and "
            "slippage at 50bps. Which data sources may I consult?",
            "Granted: Messari standardized subgraphs for yields and TVL, and the Token API "
            "for prices. I will execute through Uniswap and hold market-making positions in "
            "Aqua. This mandate is complete — review it and finalize when you are ready.",
        ]
        reply = replies[min(turns, len(replies)) - 1] if turns else (
            "Tell me what this vault should do — what it earns yield on, and what risk you "
            "are willing to take to get it."
        )
        return GenesisChatResponse(reply=reply, mandate_draft=draft)

    async def finalize(self, mandate: Mandate) -> GenesisFinalizeResponse:
        # The hash is real even in fixture mode: same canonicalization, same
        # keccak256 as live. So the value Lane E displays here is the value that
        # will be committed on-chain for this mandate, and it can be verified.
        return GenesisFinalizeResponse(
            mandate_hash=mandate_hash(mandate),
            deploy_tx=_FIXTURE_DEPLOY_TX,
            vault=_FIXTURE_VAULT,
        )
