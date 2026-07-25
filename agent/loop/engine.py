"""Snapshot + mandate in, validated decision out.

Implements `curator_schema.ports.DecisionEngine`. The port's contract is the
whole job: *"implementations MUST validate model output against
AllocationDecision and against the mandate's constraints before returning …
Nothing unvalidated reaches a Venue."*

This module is deliberately thin. Prompt construction lives in
`agent/model/prompts/`, validation and retry live in `agent/model/validation.py`,
and what remains here is the composition — which is all a decision engine should
be. Splitting it that way means the prompt can be tuned without touching the
retry logic, and the retry logic is tested with a scripted backend that needs no
prompt at all.
"""

from __future__ import annotations

from curator_schema import AllocationDecision, Mandate, MarketSnapshot, VaultState
from curator_schema.ports import ModelBackend

from ..model.prompts.curator import decision_messages, decision_schema
from ..model.validation import ValidatedDecision, generate_validated_decision

__all__ = ["LlmDecisionEngine"]


class LlmDecisionEngine:
    """The curator's judgement, behind reject-and-retry validation."""

    def __init__(self, backend: ModelBackend, *, max_attempts: int = 3) -> None:
        self._backend = backend
        self._max_attempts = max_attempts

    @property
    def backend(self) -> ModelBackend:
        return self._backend

    async def decide(self, mandate: Mandate, snapshot: MarketSnapshot) -> AllocationDecision:
        """The port method. Raises `DecisionRejected` if nothing valid was produced."""
        result = await self.decide_in_full(mandate, snapshot)
        return result.decision

    async def decide_in_full(
        self,
        mandate: Mandate,
        snapshot: MarketSnapshot,
        vault: VaultState | None = None,
    ) -> ValidatedDecision:
        """As `decide`, but keeping how many attempts it took.

        The cycle records that count on `AgentAction.model.validation_retries`.
        It is surfaced rather than hidden: retries are the honest running cost of
        a small local model, and showing them is part of the argument that the
        validation layer is load-bearing.

        `vault` is passed so the prompt can state current holdings. A model asked
        to rebalance without being told what is already held will happily propose
        buying something the vault is full of.
        """
        return await generate_validated_decision(
            self._backend,
            decision_messages(mandate, snapshot, vault),
            mandate=mandate,
            snapshot=snapshot,
            max_attempts=self._max_attempts,
            json_schema=decision_schema(),
        )
