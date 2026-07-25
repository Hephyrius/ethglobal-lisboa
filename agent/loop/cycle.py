"""One decision cycle, end to end.

    mandate -> vault state -> market snapshot -> model -> validation
            -> venue plan -> execute -> journal

**Every path through this function produces and journals an `AgentAction`.** It
raises only if the harness itself is broken. That is a deliberate contract with
Lane E: `POST /tick` renders a feed entry no matter what happened, so the dApp
never has to show a toast saying "something went wrong" — the feed says what went
wrong, and the record persists.

The five statuses mean five genuinely different things, and keeping them distinct
is what makes the feed honest:

| Status | Means | Reached the chain? |
|---|---|---|
| `executed` | the plan was submitted | yes |
| `held` | the agent chose not to act, or is in cooldown | no |
| `rejected` | output validation or a mandate limit stopped it | **no** |
| `failed` | the model, a data source, or the chain broke | maybe, partially |
| `pending` | not used here — a cycle is synchronous | — |

Collapsing `rejected` into `failed` would hide the validation layer's work, which
is the opposite of what this project is arguing.
"""

from __future__ import annotations

import logging
from time import perf_counter

from curator_schema import (
    AgentAction,
    AllocationDecision,
    ExecutionPlan,
    Mandate,
    MarketSnapshot,
    ModelProvenance,
)

from ..clock import to_utc, utcnow
from ..config import Settings
from ..mandate.amend import AmendmentRejected, apply_amendment
from ..mandate.store import MandateNotFound, MandateStore
from ..model.openai_compat import ModelUnavailable
from ..model.validation import DecisionRejected
from .engine import LlmDecisionEngine
from .idle import idle_drag_for, with_idle_fact
from .planning import PlanRejected, build_execution_plan
from .reflection import build_reflection
from .store import ActionJournal

__all__ = ["DecisionCycle"]

log = logging.getLogger(__name__)

#: How far back the reflection block looks. Wider than the five outcomes it
#: renders, because the journal is mostly holds and rejections and we want five
#: *executed* decisions if the vault has them.
_REFLECTION_HISTORY = 40


class DecisionCycle:
    """Runs one tick for one vault."""

    def __init__(
        self,
        *,
        engine: LlmDecisionEngine,
        registry,
        venues,
        vault_client,
        mandates: MandateStore,
        journal: ActionJournal,
        settings: Settings,
        performance=None,
    ) -> None:
        self._engine = engine
        self._registry = registry
        self._venues = venues
        self._chain = vault_client
        self._mandates = mandates
        self._journal = journal
        self._settings = settings
        # Optional: a cycle with no performance store still runs, it just has no
        # memory of how its past decisions worked out. That is the pre-Wave-1
        # behaviour, and it is the correct degraded state rather than a failure.
        self._performance = performance

    # ── entry point ───────────────────────────────────────────────────────

    async def run(self, vault: str) -> AgentAction:
        started = perf_counter()
        record = _Recorder(vault, self._journal, started)

        try:
            mandate = self._mandates.load(vault)
        except MandateNotFound as exc:
            return record.failed(str(exc))

        record.mandate_version = mandate.version

        try:
            state = await self._chain.state(vault)
        except Exception as exc:  # noqa: BLE001 - an unreachable chain is a failed tick
            return record.failed(f"could not read vault state: {exc}")

        # Idle capital is appended after the registry returns, so a failing
        # source still degrades exactly as before and Lane C's contract is
        # untouched. It has to be *in* the snapshot rather than only in the
        # prompt: `facts_used` is validated against the snapshot, so this is
        # what lets the model cite the number instead of asserting it.
        snapshot = with_idle_fact(await self._snapshot(mandate), mandate, state)
        record.snapshot = snapshot

        if reason := self._cooldown_reason(vault, mandate):
            return record.held(_cooldown_decision(mandate, reason), model=None)

        # ── the model ─────────────────────────────────────────────────────
        try:
            result = await self._engine.decide_in_full(
                mandate, snapshot, state, self._reflect(vault, mandate, snapshot, state)
            )
        except DecisionRejected as exc:
            return record.rejected(
                str(exc),
                model=_provenance(self._engine, retries=exc.attempts - 1),
            )
        except ModelUnavailable as exc:
            # The model said nothing, rather than saying something wrong. Not a
            # validation failure, and must not be reported as one.
            return record.failed(f"model unavailable: {exc}", model=_provenance(self._engine))

        decision = result.decision
        provenance = _provenance(self._engine, retries=result.retries)

        mandate = self._maybe_amend(vault, mandate, decision, record)

        if decision.action == "hold":
            return record.held(decision, model=provenance)

        # ── venues ────────────────────────────────────────────────────────
        try:
            plan = await build_execution_plan(decision, mandate, state, self._venues)
        except PlanRejected as exc:
            # A plan the mandate forbids is a rejection, not a failure: the
            # limits worked exactly as intended.
            return record.rejected(str(exc), decision=decision, model=provenance)

        # ── the chain ─────────────────────────────────────────────────────
        try:
            tx_hashes = await self._chain.execute(vault, plan)
        except Exception as exc:  # noqa: BLE001 - a revert is an outcome to record
            return record.failed(
                f"execution failed: {exc}", decision=decision, plan=plan, model=provenance
            )

        return record.executed(decision, plan, tx_hashes, model=provenance)

    # ── steps ─────────────────────────────────────────────────────────────

    async def _snapshot(self, mandate: Mandate) -> MarketSnapshot:
        """Consult exactly the sources the mandate permits.

        `permitted_data_sources` is the access-control mechanism: a source not
        named there is never consulted. The registry contract says a failing
        source lands in `errors` rather than raising, but this lane cannot
        guarantee another lane's implementation honours that, so a total failure
        degrades to an empty snapshot instead of killing the tick.
        """
        try:
            return await self._registry.snapshot(
                mandate.permitted_data_sources, mandate.constraints.allowed_assets
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("data registry raised; continuing with an empty snapshot (%s)", exc)
            from curator_schema import SourceError

            return MarketSnapshot(
                taken_at=utcnow(),
                facts=[],
                errors=[SourceError(source="registry", message=str(exc))],
            )

    @staticmethod
    def _hours_since_deploy(history: list[AgentAction]) -> float | None:
        """How long the book has looked the way it does now.

        Measured from the last cycle that actually moved capital. Holds and
        rejections changed nothing, so counting them would reset the clock on a
        position that never moved and make idle capital look freshly parked.
        None when nothing has ever executed — the vault has no history to price
        the drag against, and inventing a window would invent the cost too.
        """
        executed = [a for a in history if a.status == "executed"]
        if not executed:
            return None
        latest = max(to_utc(a.timestamp) for a in executed)
        return max(0.0, (utcnow() - latest).total_seconds() / 3600.0)

    def _reflect(self, vault: str, mandate: Mandate, snapshot, state) -> str:
        """The agent's own track record, rendered for the prompt.

        Never allowed to break a tick. Reflection is an *input to judgement*, not
        a precondition for acting — a vault whose performance file is missing or
        unreadable should still be curated, just amnesiacally, which is exactly
        how it behaved before this existed.

        Returns "" when there is nothing honest to say, which the prompt renders
        as nothing at all.
        """
        if self._performance is None:
            return ""
        try:
            history = self._journal.recent(vault, limit=_REFLECTION_HISTORY)
            reflection = build_reflection(
                history,
                self._performance.read(vault),
                idle_drag=idle_drag_for(
                    mandate, state, snapshot, self._hours_since_deploy(history)
                ),
            )
            return reflection.render()
        except Exception as exc:  # noqa: BLE001 - a missing memory is not a failed tick
            log.warning("could not build reflection for %s: %s", vault, exc)
            return ""

    def _cooldown_reason(self, vault: str, mandate: Mandate) -> str | None:
        """Whether the mandate's rebalance cooldown is still running.

        Checked before the model is called, not after: if the agent is not
        allowed to trade yet there is no point spending a model call to find out,
        and asking a model to decide while ignoring its answer is worse than not
        asking. Only `executed` cycles start a cooldown — holding or being
        rejected did not move capital.
        """
        cooldown = mandate.constraints.rebalance_cooldown_seconds
        if cooldown <= 0:
            return None
        last = self._journal.last_executed(vault)
        if last is None:
            return None

        elapsed = (utcnow() - to_utc(last.timestamp)).total_seconds()
        if elapsed >= cooldown:
            return None
        return (
            f"The mandate sets a {cooldown}s cooldown between rebalances and only "
            f"{int(elapsed)}s have passed since the last one, so no trade is permitted "
            "this tick."
        )

    def _maybe_amend(
        self, vault: str, mandate: Mandate, decision: AllocationDecision, record: _Recorder
    ) -> Mandate:
        """Apply a model-proposed mandate change, if it survives the invariants.

        A refused amendment does not fail the tick — the decision itself may
        still be sound under the existing mandate, and the refusal is recorded.
        """
        if decision.mandate_amendment is None:
            return mandate
        try:
            updated = apply_amendment(mandate, decision.mandate_amendment)
        except AmendmentRejected as exc:
            log.warning("mandate amendment refused for %s: %s", vault, exc)
            return mandate

        self._mandates.save(vault, updated)
        record.mandate_version_after = updated.version
        return updated


# ── recording ─────────────────────────────────────────────────────────────


def _provenance(engine: LlmDecisionEngine, retries: int = 0) -> ModelProvenance:
    backend = engine.backend
    return ModelProvenance(
        backend=getattr(backend, "name", None),
        name=getattr(backend, "model", None),
        validation_retries=retries,
    )


def _cooldown_decision(mandate: Mandate, reason: str) -> AllocationDecision:
    """A hold the agent did not author, phrased so the feed reads honestly."""
    return AllocationDecision(
        action="hold",
        reasoning=reason,
        facts_used=[],
        confidence=1.0,
    )


class _Recorder:
    """Builds, journals and returns the `AgentAction` for one cycle.

    Exists so every exit path from `run()` is one line and cannot forget to
    journal, set the duration, or carry the snapshot the decision was made from.
    """

    def __init__(self, vault: str, journal: ActionJournal, started: float) -> None:
        self._vault = vault
        self._journal = journal
        self._started = started
        self._timestamp = utcnow()
        self.snapshot: MarketSnapshot | None = None
        self.mandate_version: int | None = None
        self.mandate_version_after: int | None = None

    def _emit(self, status: str, **fields) -> AgentAction:
        action = AgentAction(
            id=f"act_{self._journal.next_index(self._vault):06d}",
            vault=self._vault,
            timestamp=self._timestamp,
            status=status,
            snapshot=self.snapshot,
            mandate_version_before=self.mandate_version,
            mandate_version_after=self.mandate_version_after or self.mandate_version,
            duration_ms=int((perf_counter() - self._started) * 1000),
            **fields,
        )
        self._journal.append(action)
        log.info("%s cycle %s -> %s", self._vault, action.id, status)
        return action

    def executed(
        self, decision, plan: ExecutionPlan, tx_hashes: list[str], *, model
    ) -> AgentAction:
        return self._emit(
            "executed", decision=decision, plan=plan, tx_hashes=tx_hashes, model=model
        )

    def held(self, decision, *, model) -> AgentAction:
        return self._emit("held", decision=decision, model=model)

    def rejected(self, error: str, *, decision=None, model=None) -> AgentAction:
        return self._emit("rejected", error=error, decision=decision, model=model)

    def failed(self, error: str, *, decision=None, plan=None, model=None) -> AgentAction:
        return self._emit("failed", error=error, decision=decision, plan=plan, model=model)
