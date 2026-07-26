"""The seam between HTTP routes and everything behind them.

Route handlers depend on these two Protocols and nothing else. That is what lets
fixture mode and live mode share byte-identical handlers: `agent.api.deps` picks
the implementation, the routes never learn which one they got, and the endpoint
Lane E integrated against in hour 2 is the same endpoint that runs at the demo.

These are deliberately *application* services rather than API helpers — they
orchestrate the mandate store, the decision loop and the chain client, none of
which should be reachable from a route handler directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from curator_schema import AgentAction, Mandate, VaultPerformance, VaultState

from ..api.schemas import (
    ArchetypeDeployResponse,
    ArchetypeSummary,
    ChatMessage,
    GenesisChatResponse,
    GenesisFinalizeResponse,
    MandateVerificationResponse,
)

__all__ = ["ArchetypeService", "GenesisService", "VaultService"]


@runtime_checkable
class GenesisService(Protocol):
    """The one-time strategy-creation conversation.

    Genesis is a single event: it produces the mandate, and after it the human
    deployer has no further say (locked decision, plans/initiate_plan.md §2).
    """

    async def chat(self, messages: list[ChatMessage]) -> GenesisChatResponse:
        """One turn of the mandate-design conversation.

        Returns the assistant's reply plus the mandate as understood so far.
        The draft is advisory and may be incomplete or absent — it is a preview
        for the user, not a commitment.
        """
        ...

    async def finalize(
        self, mandate: Mandate, deployer: str | None = None
    ) -> GenesisFinalizeResponse:
        """Crystallize the mandate and deploy its vault.

        Hashes the canonical mandate, deploys a vault via the factory bound to
        that hash, and persists the mandate under the deployed address so the
        agent can load it on every subsequent tick.

        `deployer` is Lane A's §A1 attribution field, forwarded to
        `createVault` when the deployed factory has one. The agent submits the
        transaction either way, so it records who asked and is never proof.
        """
        ...

    def available_sources(self) -> list[str]:
        """Data-source registry keys the user may grant in a mandate."""
        ...

    def available_venues(self) -> list[str]:
        """Venue keys the mandate may permit."""
        ...


@runtime_checkable
class ArchetypeService(Protocol):
    """Genesis with the model in the seat the human normally occupies.

    Separate from `GenesisService` because the two differ in the one way that
    matters: genesis has a person reading the mandate before it deploys, and
    this has nobody. Everything specific to that — the envelope check, the
    regeneration, the record of which archetype made which vault — belongs on
    this side of the seam and not in a flag on the other one.
    """

    def summaries(self) -> list[ArchetypeSummary]:
        """Every envelope the dApp may offer, with how many vaults each has made."""
        ...

    async def deploy(self, key: str, deployer: str | None = None) -> ArchetypeDeployResponse:
        """Generate a mandate inside this envelope and put it on-chain.

        Raises `KeyError` for an unknown archetype and
        `agent.archetypes.GenerationFailed` when nothing generated sat inside
        the bounds. **Never returns a deployed vault whose mandate escaped its
        envelope** — that is the whole contract, because nothing else reads the
        mandate before the transaction is signed.
        """
        ...


@runtime_checkable
class VaultService(Protocol):
    """Everything the dApp asks about one live vault."""

    async def state(self, vault: str) -> VaultState:
        """Current on-chain state."""
        ...

    async def decisions(self, vault: str, limit: int) -> list[AgentAction]:
        """Most recent decision cycles, newest first.

        Includes `rejected` and `failed` actions. They are the evidence that
        output validation is load-bearing and they render in the decision feed.
        """
        ...

    async def tick(self, vault: str) -> AgentAction:
        """Run one decision cycle and return what happened.

        Always returns an AgentAction — a cycle that held, was rejected at
        validation, or failed on-chain is still a recorded outcome, never an
        HTTP error. The only 4xx/5xx from this route are transport-level.
        """
        ...

    async def mandate(self, vault: str) -> Mandate:
        """The mandate this vault is curated under."""
        ...

    async def mandate_verification(self, vault: str) -> MandateVerificationResponse:
        """Whether the stored mandate still hashes to what the chain recorded.

        Not a boolean, because since Wave 2 a mismatch has three causes and only
        one of them means something is wrong (cross-lane #71). See
        `agent/mandate/hashing.py`.
        """
        ...

    async def vault_yield(self, vault: str):
        """What the vault earns **now**, position by position.

        The complement to `performance()`, not a duplicate of it: that one is
        realised and stays null until the series spans a day, so it is blank
        for the whole of a fresh deployment while the vault is visibly earning.
        This reads the current rate on what is held, so it is populated from
        the first tick.

        Idle capital is `0.0`. A position whose rate could not be found is
        `None` — the two are different claims and must not be collapsed.
        """
        ...

    async def performance(self, vault: str, window: str = "all") -> VaultPerformance:
        """Share-price history plus the risk figures derived from it.

        Points are observations, never interpolations. Every summary figure is
        None rather than zero when the series cannot support it — the caller is
        expected to render "not enough history" rather than a number.
        """
        ...
