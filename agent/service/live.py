"""Live services — the real loop behind the frozen routes.

Selected by `AGENT_MODE=live`. Same ports, same route handlers, same response
shapes as fixture mode; only the objects behind the seam change.

Assembly happens here rather than in the routes so that every dependency of the
decision cycle — model backend, data registry, venues, chain client, mandate
store, journal — is visible in one place.
"""

from __future__ import annotations

import logging

from curator_schema import AgentAction, Mandate, VaultPerformance, VaultState

from ..api.schemas import (
    ChatMessage,
    GenesisChatResponse,
    GenesisFinalizeResponse,
    MandateDraft,
)
from ..config import Settings
from ..loop.cycle import DecisionCycle
from ..loop.engine import LlmDecisionEngine
from ..loop.store import ActionJournal
from ..mandate.hashing import mandate_hash
from ..mandate.store import MandateStore
from ..mandate.universe import offerable_assets
from ..model.backends import build_backend
from ..model.extraction import ExtractionError, extract_json_object
from ..model.openai_compat import ModelUnavailable
from ..model.prompts.genesis import genesis_messages, genesis_schema
from ..performance import PerformanceStore, point_from_state, summarize
from ..performance.window import window_points

__all__ = ["LiveVaultService", "LiveGenesisService"]

log = logging.getLogger(__name__)


def _build_chain_client(settings: Settings):
    """Lane A's vault, or a stub if the ABIs are not published yet.

    Falls back rather than failing: during the build, live mode with an
    incomplete `contracts/out/` is a normal state, and the loop is still worth
    exercising end to end without it.
    """
    try:
        from ..chain.vault_client import Web3VaultClient

        return Web3VaultClient(settings)
    except Exception as exc:  # noqa: BLE001
        from ..chain.stub import StubVaultClient

        log.warning("falling back to the stub vault client (%s)", exc)
        return StubVaultClient()


class LiveVaultService:
    """`VaultService` over the real decision cycle."""

    def __init__(self, settings: Settings) -> None:
        from ..api.deps import get_data_registry, get_venue_registry

        self._settings = settings
        self._mandates = MandateStore(settings.state_dir)
        self._journal = ActionJournal(settings.state_dir)
        self._performance = PerformanceStore(settings.state_dir)
        self._chain = _build_chain_client(settings)
        self._cycle = DecisionCycle(
            engine=LlmDecisionEngine(
                build_backend(settings), max_attempts=settings.max_validation_retries
            ),
            registry=get_data_registry(),
            venues=get_venue_registry(),
            vault_client=self._chain,
            mandates=self._mandates,
            journal=self._journal,
            settings=settings,
            # The same store the /performance route serves, so the reflection
            # the model reads and the chart a depositor reads are the same data.
            performance=self._performance,
        )

    async def state(self, vault: str) -> VaultState:
        state = await self._chain.state(vault)
        self._record(state, source="sampler")
        return state

    async def mandate(self, vault: str) -> Mandate:
        return self._mandates.load(vault)

    async def decisions(self, vault: str, limit: int) -> list[AgentAction]:
        return self._journal.recent(vault, limit)

    async def tick(self, vault: str) -> AgentAction:
        action = await self._cycle.run(vault)
        # After the cycle, not before: a tick that executed has moved the book,
        # and the point worth recording is where it ended up. The pre-trade
        # state was already recorded by whatever read it last.
        try:
            self._record(await self._chain.state(vault), source="tick")
        except Exception as exc:  # noqa: BLE001 - never turn a good tick into a failure
            log.warning("could not record performance after tick on %s: %s", vault, exc)
        return action

    async def performance(self, vault: str, window: str = "all") -> VaultPerformance:
        points = window_points(self._performance.read(vault), window)
        return VaultPerformance(
            vault=vault, points=points, summary=summarize(vault, points)
        )

    def _record(self, state: VaultState, *, source: str) -> None:
        """Append one observation. Never allowed to break the request.

        Recording rides on `state()` rather than running as its own background
        loop for two reasons: the read has already happened, so the point is
        free; and the dApp polls `state()` while anyone is watching, which is
        exactly when the series is worth having. Gaps while nobody is watching
        are recoverable — `backfill.py` reconstructs them from chain history.
        """
        try:
            self._performance.append(
                state.address, point_from_state(state, source=source)  # type: ignore[arg-type]
            )
        except Exception as exc:  # noqa: BLE001 - a chart is never worth a 500
            log.warning("could not record performance for %s: %s", state.address, exc)


class LiveGenesisService:
    """`GenesisService` driving the real model."""

    def __init__(self, settings: Settings) -> None:
        from ..api.deps import get_data_registry, get_venue_registry

        self._settings = settings
        self._backend = build_backend(settings)
        self._registry = get_data_registry()
        self._venues = get_venue_registry()
        self._mandates = MandateStore(settings.state_dir)
        self._chain = _build_chain_client(settings)

    def available_sources(self) -> list[str]:
        try:
            return list(self._registry.available())
        except Exception as exc:  # noqa: BLE001
            log.warning("data registry could not list sources (%s)", exc)
            return []

    def available_venues(self) -> list[str]:
        available = getattr(self._venues, "available", None)
        if callable(available):
            try:
                return list(available())
            except Exception as exc:  # noqa: BLE001
                log.warning("venue registry could not list venues (%s)", exc)
        return ["uniswap", "aqua"]

    async def chat(self, messages: list[ChatMessage]) -> GenesisChatResponse:
        """One conversational turn.

        Degrades rather than fails: a response that is not the expected envelope
        is still shown to the user as plain text with no draft update. A human is
        present and can simply restate themselves — unlike the decision loop,
        where there is nobody to recover and rejection is the only safe answer.
        """
        conversation = genesis_messages(
            messages,
            self.available_sources(),
            self.available_venues(),
            offerable_assets(),
        )
        try:
            raw = await self._backend.complete(
                conversation, json_schema=genesis_schema(), temperature=0.3
            )
        except ModelUnavailable as exc:
            log.error("genesis chat model unavailable: %s", exc)
            return GenesisChatResponse(
                reply=(
                    "I could not reach the local model just now, so I cannot continue "
                    "designing the mandate. Check that Ollama is running, then try again."
                )
            )

        try:
            payload = extract_json_object(raw, expect_key="reply")
        except ExtractionError:
            return GenesisChatResponse(reply=raw.strip())

        reply = str(payload.get("reply") or raw.strip())
        draft_payload = payload.get("mandate_draft")
        if not isinstance(draft_payload, dict):
            return GenesisChatResponse(reply=reply)

        try:
            draft = MandateDraft.model_validate(draft_payload)
        except ValueError as exc:
            # The conversation is more valuable than the preview. Drop the bad
            # draft, keep talking; `finalize` validates strictly anyway.
            log.info("discarding an unparseable mandate draft: %s", exc)
            return GenesisChatResponse(reply=reply)

        return GenesisChatResponse(reply=reply, mandate_draft=draft)

    async def finalize(self, mandate: Mandate) -> GenesisFinalizeResponse:
        """Hash the mandate, deploy its vault, and persist it under that address.

        The order matters: the hash is computed from the mandate as given, the
        vault is deployed bound to that hash, and only then is the mandate stored
        under the deployed address. A mandate saved before a failed deploy would
        leave a vault-less mandate the agent might later tick against.
        """
        digest = mandate_hash(mandate)
        vault, deploy_tx = await self._chain.deploy(mandate, digest)
        self._mandates.save(vault, mandate)
        log.info("genesis complete: vault %s bound to mandate %s", vault, digest[:10])
        return GenesisFinalizeResponse(mandate_hash=digest, deploy_tx=deploy_tx, vault=vault)
