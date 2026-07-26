"""Live services — the real loop behind the frozen routes.

Selected by `AGENT_MODE=live`. Same ports, same route handlers, same response
shapes as fixture mode; only the objects behind the seam change.

Assembly happens here rather than in the routes so that every dependency of the
decision cycle — model backend, data registry, venues, chain client, mandate
store, journal — is visible in one place.
"""

from __future__ import annotations

import logging

from curator_schema import (
    AgentAction,
    Mandate,
    VaultPerformance,
    VaultState,
    load_archetype,
    load_archetypes,
)

from ..api.schemas import (
    PositionYieldResponse,
    VaultYieldResponse,
    ArchetypeDeployResponse,
    ArchetypeSummary,
    ChatMessage,
    GenesisChatResponse,
    GenesisFinalizeResponse,
    MandateDraft,
    MandateVerificationResponse,
)
from ..archetypes import ArchetypeStore, Deployment, generate_mandate, market_context
from ..chain.aqua_positions import AquaPositionStore
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
from ..yields import compute_vault_yield
from ..performance.window import window_points
from .verification import verification_response

__all__ = ["LiveArchetypeService", "LiveVaultService", "LiveGenesisService"]

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
        # Held as well as passed to the cycle: `/yield` reads the same registry
        # so the rate on the vault page is the rate the agent decided on, not a
        # second opinion from a different set of sources.
        self._registry = get_data_registry()
        self._cycle = DecisionCycle(
            engine=LlmDecisionEngine(
                build_backend(settings), max_attempts=settings.max_validation_retries
            ),
            registry=self._registry,
            venues=get_venue_registry(),
            vault_client=self._chain,
            mandates=self._mandates,
            journal=self._journal,
            settings=settings,
            # The same store the /performance route serves, so the reflection
            # the model reads and the chart a depositor reads are the same data.
            performance=self._performance,
            # The same store `Web3VaultClient` reads when it builds a
            # `VaultState`, so a ship recorded by the cycle is on screen at the
            # next `/state` and available to `dock()` on the next tick.
            aqua_positions=AquaPositionStore(settings.state_dir),
        )

    async def state(self, vault: str) -> VaultState:
        state = await self._chain.state(vault)
        self._record(state, source="sampler")
        return state

    async def mandate(self, vault: str) -> Mandate:
        return self._mandates.load(vault)

    async def mandate_verification(self, vault: str) -> MandateVerificationResponse:
        """Recompute the hash and account for any difference from the chain.

        The stored bytes are read separately from the parsed mandate on purpose:
        a schema field with a non-`None` default materializes on parse, so the
        model alone cannot say whether this vault's mandate ever mentioned it.
        """
        mandate = self._mandates.load(vault)
        stored = self._mandates.load_raw(vault) or ""
        on_chain = None
        try:
            on_chain = (await self._chain.state(vault)).mandate_hash
        except Exception as exc:  # noqa: BLE001
            # An unreachable chain is "cannot verify", not "verification
            # failed" — reporting a mismatch here would accuse a vault of
            # something the RPC outage is responsible for.
            log.warning("could not read %s's on-chain mandate hash: %s", vault, exc)
        return verification_response(vault, stored, mandate, on_chain)

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

    async def vault_yield(self, vault: str) -> VaultYieldResponse:
        """Current rate on each holding, from the same sources the agent reads.

        Deliberately uses the *mandate's* granted sources rather than every
        registered one: a rate the agent is not permitted to consult is not the
        rate it is acting on, and showing it on the vault page would imply a
        decision input that does not exist.

        A snapshot failure degrades to "no rates known" rather than a 500 — the
        holdings and their weights are still worth showing, and `coverage: 0`
        says plainly that the blend covers nothing.
        """
        state = await self._chain.state(vault)

        facts: list = []
        try:
            mandate = self._mandates.load(vault)
            snapshot = await self._registry.snapshot(
                mandate.permitted_data_sources, mandate.constraints.allowed_assets
            )
            facts = list(snapshot.facts)
        except Exception as exc:  # noqa: BLE001 - a rate is never worth a 500
            log.warning("could not read yields for %s: %s", vault, exc)

        result = compute_vault_yield(state, facts)
        return VaultYieldResponse(
            vault=result.vault,
            positions=[
                PositionYieldResponse(
                    token=p.token,
                    symbol=p.symbol,
                    represents=p.represents,
                    venue=p.venue,
                    value_in_asset=str(p.value_in_asset),
                    apy=p.apy,
                    source=p.source,
                    fact_id=p.fact_id,
                )
                for p in result.positions
            ],
            weighted_apy=result.weighted_apy,
            coverage=result.coverage,
        )

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
        """Venue keys the genesis UI may offer.

        Three rungs, because the venue seam is a bare `get_venue(key)` lookup
        function with no introspection method — so the obvious `.available()`
        never resolves, and the hardcoded fallback silently became the answer.

        That was a real bug, caught by reading `GET /genesis/sources` after
        adding Aave: it reported `uniswap, aqua`, meaning **the third venue
        could never be granted in a mandate and the agent could never lend.**
        A fallback that happens to be right is indistinguishable from one that
        has gone stale, which is exactly what happened here.
        """
        available = getattr(self._venues, "available", None)
        if callable(available):
            try:
                return list(available())
            except Exception as exc:  # noqa: BLE001
                log.warning("venue registry could not list venues (%s)", exc)

        # The registry's own published tuple, rather than a copy of it.
        try:
            from venues.registry import VENUES

            return list(VENUES)
        except Exception as exc:  # noqa: BLE001 - venues is an optional seam
            log.warning("venue package unavailable (%s); offering the frozen pair", exc)

        # Last resort only: the two venues every deployment has had since Wave 0.
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
            #
            # ⚠️ WARNING, not INFO, and the distinction cost hours. Discarding
            # the draft does not degrade the flow, it *ends* it: the dApp builds
            # its draft panel and arms its deploy button purely from
            # accumulated `mandate_draft`, so a turn that drops one is a turn
            # the user cannot progress past. Meanwhile the reply still reads
            # perfectly, the route still answers 200, and `/health` stays green.
            # Logged at INFO — a level uvicorn does not emit here — that left
            # exactly zero evidence anywhere that the genesis flow was dead.
            log.warning(
                "discarding an unparseable mandate draft — the dApp cannot advance "
                "without one, check genesis_schema() matches MandateDraft: %s",
                exc,
            )
            return GenesisChatResponse(reply=reply)

        return GenesisChatResponse(reply=reply, mandate_draft=draft)

    async def finalize(
        self, mandate: Mandate, deployer: str | None = None
    ) -> GenesisFinalizeResponse:
        """Hash the mandate, deploy its vault, and persist it under that address.

        The order matters: the hash is computed from the mandate as given, the
        vault is deployed bound to that hash, and only then is the mandate stored
        under the deployed address. A mandate saved before a failed deploy would
        leave a vault-less mandate the agent might later tick against.
        """
        digest = mandate_hash(mandate)
        # Forwarded, not stored: attribution is Lane A's event (SS A1), and a
        # second copy in this lane would be a second thing to disagree with it.
        vault, deploy_tx = await self._chain.deploy(mandate, digest, deployer)
        self._mandates.save(vault, mandate)
        log.info("genesis complete: vault %s bound to mandate %s", vault, digest[:10])
        return GenesisFinalizeResponse(mandate_hash=digest, deploy_tx=deploy_tx, vault=vault)


class LiveArchetypeService:
    """`ArchetypeService` over the real model and the real factory.

    Reuses `LiveGenesisService.finalize` for the last step rather than
    reimplementing it, which is the point of §4 B1's *"deploy through the
    existing genesis path"*: hashing, `createVault` and the mandate store are
    identical, so an archetype vault is indistinguishable from a curated one
    afterwards and every downstream route already works on it.
    """

    def __init__(self, settings: Settings) -> None:
        from ..api.deps import get_data_registry

        self._settings = settings
        self._backend = build_backend(settings)
        self._genesis = LiveGenesisService(settings)
        self._store = ArchetypeStore(settings.state_dir)
        self._registry = get_data_registry()

    def summaries(self) -> list[ArchetypeSummary]:
        return [
            _summary(archetype, len(self._store.deployments(archetype.key)))
            for archetype in load_archetypes()
        ]

    async def deploy(self, key: str, deployer: str | None = None) -> ArchetypeDeployResponse:
        archetype = load_archetype(key)  # KeyError names what is available
        generated = await generate_mandate(
            self._backend,
            archetype,
            emphasis_index=self._store.next_emphasis_index(key, len(archetype.emphases)),
            seen=self._store.signatures(key),
            known_names=self._store.names(key),
            context=market_context(await self._snapshot(archetype)),
            max_attempts=self._settings.archetype_attempts,
        )

        # Only now. Everything above can fail, and a failure above must leave no
        # trace on-chain — which is the difference between "regenerate" and
        # "never deploy".
        finalized = await self._genesis.finalize(generated.mandate, deployer)
        self._store.record(
            Deployment(
                vault=finalized.vault,
                archetype=key,
                name=generated.mandate.name,
                signature=generated.signature,
                emphasis_index=generated.emphasis_index,
                deployer=deployer,
            )
        )
        log.info(
            "archetype %s deployed %s in %d attempt(s)", key, finalized.vault, generated.attempts
        )
        return ArchetypeDeployResponse(
            vault=finalized.vault,
            mandate_hash=finalized.mandate_hash,
            deploy_tx=finalized.deploy_tx,
            archetype=key,
            mandate=generated.mandate,
            emphasis=generated.emphasis,
            attempts=generated.attempts,
            rejections=generated.rejections,
            collided=generated.collided,
        )

    async def _snapshot(self, archetype):
        """What the market looks like right now, as generation seed only.

        Degrades to nothing rather than failing the click: the snapshot varies
        the generation, it does not authorise it, so an unreachable data source
        costs some variety and no correctness. Asking for the archetype's own
        permitted sources keeps this inside the same access-control rule every
        other read obeys.
        """
        try:
            return await self._registry.snapshot(
                list(archetype.permitted_data_sources.subset_of),
                list(archetype.allowed_assets.subset_of),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("no market context for archetype %s (%s)", archetype.key, exc)
            return None


def _summary(archetype, deployed: int) -> ArchetypeSummary:
    return ArchetypeSummary(
        key=archetype.key,
        name=archetype.name,
        headline=archetype.headline,
        tradeoff=archetype.tradeoff,
        base_asset=archetype.base_asset,
        allowed_assets=list(archetype.allowed_assets.subset_of),
        permitted_venues=list(archetype.permitted_venues.subset_of),
        risk_postures=list(archetype.risk_postures),
        constraint_ranges={
            name: {"min": r.min, "max": r.max}
            for name, r in archetype.constraint_ranges.items()
        },
        deployed=deployed,
    )
