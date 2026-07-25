"""The decision cycle: every path produces and journals an `AgentAction`.

That contract is what lets Lane E render a feed entry for every tick instead of
an error toast, so it is tested as a property across all of them rather than
just on the happy path.

The distinction between `rejected` and `failed` gets its own tests. Collapsing
them would hide the validation layer's work, which is the thing this project is
arguing for.
"""

from __future__ import annotations

import json

import pytest

from agent import fixtures
from agent.chain.stub import StubVaultClient
from agent.config import Settings
from agent.loop.cycle import DecisionCycle
from agent.loop.engine import LlmDecisionEngine
from agent.loop.idle import HARNESS_SOURCE, IDLE_FACT_ID
from agent.loop.store import ActionJournal
from agent.mandate.store import MandateStore
from agent.model.backends.scripted import ScriptedBackend
from agent.model.openai_compat import ModelUnavailable
from agent.providers.fixture_data import FixtureDataRegistry
from agent.providers.fixture_venue import FixtureVenueRegistry

VAULT = "0x1111111111111111111111111111111111111111"


def _good_decision() -> str:
    """A rebalance that is coherent with the golden vault state.

    The golden *decision* fixture targets 70/30 on a vault already at 70/30 and
    then trades, which validation layer 6 now correctly rejects: a target you
    trade away from is not a target. The two golden files were written to
    exercise shapes, not to be consistent as a pair. So this states a 50/50
    target and sells the ~29% of USDC that lands there.
    """
    golden = fixtures.allocation_decision()
    return golden.model_copy(
        update={
            "target_allocations": [
                {"asset": "USDC", "weight": 0.5},
                {"asset": "WETH", "weight": 0.5},
            ],
            "venue_intents": [
                {
                    "venue": "uniswap",
                    "kind": "swap",
                    "token_in": "USDC",
                    "token_out": "WETH",
                    "pct_of_holdings": 0.29,
                }
            ],
        }
    ).model_dump_json(exclude_none=True)


def _hold_decision() -> str:
    return json.dumps(
        {
            "action": "hold",
            "reasoning": "The spread has not moved and the vault is already sized correctly.",
            "facts_used": ["f1", "f2"],
            "confidence": 0.8,
        }
    )


def _build(tmp_path, responses, *, mandate=None, chain=None, venues=None):
    """A cycle wired to fixtures and a scripted model, on a throwaway state dir."""
    settings = Settings(state_dir=tmp_path)
    mandates = MandateStore(tmp_path)
    mandates.save(VAULT, mandate or fixtures.mandate())
    journal = ActionJournal(tmp_path)

    backend = ScriptedBackend(responses)
    cycle = DecisionCycle(
        engine=LlmDecisionEngine(backend, max_attempts=2),
        registry=FixtureDataRegistry(),
        venues=venues if venues is not None else FixtureVenueRegistry(),
        vault_client=chain or StubVaultClient(),
        mandates=mandates,
        journal=journal,
        settings=settings,
    )
    return cycle, journal, backend, mandates


# ── the happy path ────────────────────────────────────────────────────────


async def test_a_good_decision_executes_and_is_journaled(tmp_path):
    cycle, journal, _, _ = _build(tmp_path, [_good_decision()])

    action = await cycle.run(VAULT)

    assert action.status == "executed"
    assert action.decision is not None and action.decision.action == "rebalance"
    assert action.plan is not None and action.plan.steps
    assert action.tx_hashes, "an executed cycle must record what it submitted"
    assert action.snapshot is not None, "the feed needs the data the decision was made from"
    assert action.duration_ms is not None

    stored = journal.recent(VAULT, 10)
    assert len(stored) == 1 and stored[0].id == action.id


async def test_the_snapshot_only_contains_permitted_sources(tmp_path):
    """`permitted_data_sources` is the access-control mechanism, not a hint.

    It governs which **external providers** the agent may consult. The harness's
    own derived facts are exempt and deliberately so: `vault:idle-capital` is
    computed from the vault's on-chain state, which the agent already holds and
    did not have to be granted. Marking it `harness` rather than borrowing a
    provider's name is what keeps that distinction legible in the feed — a
    derived number must never be attributable to The Graph.
    """
    mandate = fixtures.mandate().model_copy(update={"permitted_data_sources": ["messari"]})
    cycle, _, _, _ = _build(tmp_path, [_good_decision()], mandate=mandate)

    action = await cycle.run(VAULT)

    providers = {f.source for f in action.snapshot.facts if f.source != HARNESS_SOURCE}
    assert providers == {"messari"}, f"consulted a source the mandate did not grant: {providers}"


async def test_the_snapshot_carries_the_idle_capital_fact(tmp_path):
    """Citable, so the feed can show "deployed because 68% was idle" with the
    number attached rather than the agent asserting it."""
    cycle, _, _, _ = _build(tmp_path, [_good_decision()])

    action = await cycle.run(VAULT)

    idle = [f for f in action.snapshot.facts if f.id == IDLE_FACT_ID]
    assert len(idle) == 1, "exactly one idle fact per tick"
    # Golden vault: 70% uncommitted USDC, 20% cash floor -> 50% idle.
    assert idle[0].value == 0.5
    assert idle[0].source == HARNESS_SOURCE


async def test_a_decision_may_cite_the_idle_fact(tmp_path):
    """Layer 4 validates `facts_used` against the snapshot, so a fact that is
    not in it cannot be cited. This is what makes the number un-inventable."""
    citing = json.dumps(
        {
            "action": "hold",
            "reasoning": "Half the book is idle but the yields on offer do not cover the move.",
            "facts_used": [IDLE_FACT_ID],
            "confidence": 0.7,
        }
    )
    cycle, _, _, _ = _build(tmp_path, [citing])

    action = await cycle.run(VAULT)

    assert action.status == "held"
    assert action.decision.facts_used == [IDLE_FACT_ID]


# ── holding ───────────────────────────────────────────────────────────────


async def test_a_hold_records_a_decision_but_no_plan(tmp_path):
    cycle, journal, _, _ = _build(tmp_path, [_hold_decision()])

    action = await cycle.run(VAULT)

    assert action.status == "held"
    assert action.decision.action == "hold"
    assert action.plan is None
    assert action.tx_hashes == []
    assert journal.recent(VAULT, 5)[0].status == "held"


# ── rejection vs failure: the distinction that matters ────────────────────


async def test_unrecoverable_model_output_is_rejected_not_failed(tmp_path):
    """Nothing reaches the chain, and the record says validation stopped it."""
    cycle, journal, _, _ = _build(tmp_path, ["I think buy ETH", "still not json"])

    action = await cycle.run(VAULT)

    assert action.status == "rejected"
    assert action.plan is None
    assert action.tx_hashes == []
    assert action.error
    assert action.model.validation_retries > 0
    assert journal.recent(VAULT, 5)[0].status == "rejected", "rejections are kept, not discarded"


async def test_a_mandate_breach_is_rejected(tmp_path):
    breach = json.dumps(
        {
            "action": "rebalance",
            "reasoning": "Rotating everything into cbETH for the higher yield.",
            "facts_used": ["f1"],
            "target_allocations": [{"asset": "cbETH", "weight": 1.0}],
            "venue_intents": [
                {
                    "venue": "uniswap",
                    "kind": "swap",
                    "token_in": "USDC",
                    "token_out": "cbETH",
                    "pct_of_holdings": 1.0,
                }
            ],
        }
    )
    cycle, _, _, _ = _build(tmp_path, [breach, breach])

    action = await cycle.run(VAULT)

    assert action.status == "rejected"
    assert "cbETH" in action.error
    assert action.tx_hashes == []


async def test_an_unreachable_model_fails_rather_than_rejects(tmp_path):
    """The model said nothing, rather than saying something wrong.

    Reporting a dead Ollama as a validation rejection would make the feed
    misreport why the tick produced nothing.
    """

    class DeadBackend:
        name = "ollama"
        model = "qwen2.5:14b-instruct"

        async def complete(self, messages, *, json_schema=None, temperature=0.0):
            raise ModelUnavailable("could not reach http://localhost:11434/v1")

    cycle, journal, _, _ = _build(tmp_path, [_good_decision()])
    cycle._engine = LlmDecisionEngine(DeadBackend())

    action = await cycle.run(VAULT)

    assert action.status == "failed"
    assert "unavailable" in action.error
    assert journal.recent(VAULT, 5)[0].status == "failed"


async def test_a_reverting_chain_is_a_failure_that_keeps_the_plan(tmp_path):
    """A revert is an outcome to record — with the plan, so it is diagnosable."""

    class RevertingChain(StubVaultClient):
        async def execute(self, vault, plan):
            raise RuntimeError("UniversalRouter V3TooLittleReceived")

    cycle, _, _, _ = _build(tmp_path, [_good_decision()], chain=RevertingChain())

    action = await cycle.run(VAULT)

    assert action.status == "failed"
    assert action.plan is not None, "the plan that failed must be inspectable"
    assert "V3TooLittleReceived" in action.error


async def test_a_missing_venue_adapter_is_rejected(tmp_path):
    cycle, _, _, _ = _build(tmp_path, [_good_decision()], venues={})

    action = await cycle.run(VAULT)

    assert action.status == "rejected"
    assert "uniswap" in action.error


async def test_a_plan_breaching_the_slippage_ceiling_is_rejected(tmp_path):
    """The one mandate limit only a quote can reveal."""

    class ExpensiveVenue:
        key = "uniswap"

        async def plan(self, intent, vault):
            return fixtures.execution_plan().model_copy(
                update={"expected_slippage_bps": 900, "quote_expires_at": None}
            )

    cycle, _, _, _ = _build(tmp_path, [_good_decision()], venues={"uniswap": ExpensiveVenue()})

    action = await cycle.run(VAULT)

    assert action.status == "rejected"
    assert "slippage" in action.error
    assert action.tx_hashes == []


async def test_a_stale_quote_is_never_submitted(tmp_path):
    from datetime import timedelta

    from agent.clock import utcnow

    class StaleVenue:
        key = "uniswap"

        async def plan(self, intent, vault):
            return fixtures.execution_plan().model_copy(
                update={"quote_expires_at": utcnow() - timedelta(minutes=5)}
            )

    cycle, _, _, _ = _build(tmp_path, [_good_decision()], venues={"uniswap": StaleVenue()})

    action = await cycle.run(VAULT)

    assert action.status == "rejected"
    assert "expired" in action.error


async def test_a_missing_mandate_fails_cleanly(tmp_path):
    """Ticking a vault this harness never deployed must not raise."""
    settings = Settings(state_dir=tmp_path)
    cycle = DecisionCycle(
        engine=LlmDecisionEngine(ScriptedBackend([_good_decision()])),
        registry=FixtureDataRegistry(),
        venues=FixtureVenueRegistry(),
        vault_client=StubVaultClient(),
        mandates=MandateStore(tmp_path),
        journal=ActionJournal(tmp_path),
        settings=settings,
    )

    action = await cycle.run("0x2222222222222222222222222222222222222222")

    assert action.status == "failed"
    assert "no mandate" in action.error


# ── the cooldown ──────────────────────────────────────────────────────────


async def test_the_cooldown_holds_without_calling_the_model(tmp_path):
    """Asking a model to decide and then ignoring its answer is worse than not asking."""
    cycle, journal, backend, _ = _build(tmp_path, [_good_decision(), _good_decision()])

    first = await cycle.run(VAULT)
    assert first.status == "executed"
    calls_after_first = len(backend.calls)

    second = await cycle.run(VAULT)

    assert second.status == "held"
    assert "cooldown" in second.decision.reasoning
    assert len(backend.calls) == calls_after_first, "the model must not be called during cooldown"
    assert second.snapshot is not None, "the feed still shows what was observed"


async def test_only_executed_cycles_start_a_cooldown(tmp_path):
    """A hold did not move capital, so it must not block the next tick."""
    mandate = fixtures.mandate()
    cycle, _, _, _ = _build(tmp_path, [_hold_decision(), _good_decision()])

    first = await cycle.run(VAULT)
    second = await cycle.run(VAULT)

    assert first.status == "held"
    assert second.status == "executed", "a hold must not trigger the rebalance cooldown"
    assert mandate.constraints.rebalance_cooldown_seconds > 0


# ── mandate amendment ─────────────────────────────────────────────────────


async def test_a_valid_amendment_is_applied_and_versioned(tmp_path):
    amended = json.dumps(
        {
            "action": "hold",
            "reasoning": "Widening the cash floor after seeing utilization spike.",
            "facts_used": ["f4"],
            "mandate_amendment": {
                "rationale": "Utilization at 91% raises redemption risk; hold more cash.",
                "patch": {
                    "constraints": {
                        "allowed_assets": ["USDC", "WETH"],
                        "max_slippage_bps": 50,
                        "max_position_pct": 0.6,
                        "min_cash_pct": 0.3,
                        "rebalance_cooldown_seconds": 3600,
                        "max_actions_per_tick": 2,
                    }
                },
            },
        }
    )
    cycle, _, _, mandates = _build(tmp_path, [amended])

    action = await cycle.run(VAULT)

    assert action.mandate_version_before == 1
    assert action.mandate_version_after == 2
    assert mandates.load(VAULT).constraints.min_cash_pct == 0.3


async def test_an_amendment_touching_the_base_asset_is_refused(tmp_path):
    """The ERC-4626 asset is fixed at deployment; the tick continues regardless."""
    amended = json.dumps(
        {
            "action": "hold",
            "reasoning": "Switching the vault to WETH denomination.",
            "facts_used": ["f5"],
            "mandate_amendment": {
                "rationale": "WETH is the better base asset.",
                "patch": {"base_asset": "WETH"},
            },
        }
    )
    cycle, _, _, mandates = _build(tmp_path, [amended])

    action = await cycle.run(VAULT)

    assert action.status == "held", "a refused amendment must not fail the tick"
    assert mandates.load(VAULT).base_asset == "USDC"
    assert mandates.load(VAULT).version == 1


# ── the property that holds across every path ─────────────────────────────


@pytest.mark.parametrize(
    ("label", "responses"),
    [
        ("executed", [_good_decision()]),
        ("held", [_hold_decision()]),
        ("rejected", ["garbage", "more garbage"]),
    ],
)
async def test_every_path_returns_and_journals_an_action(tmp_path, label, responses):
    cycle, journal, _, _ = _build(tmp_path, responses)

    action = await cycle.run(VAULT)

    assert action.vault == VAULT
    assert action.id
    assert action.timestamp.tzinfo is not None, "timestamps must be tz-aware for the wire format"
    assert journal.count(VAULT) == 1
