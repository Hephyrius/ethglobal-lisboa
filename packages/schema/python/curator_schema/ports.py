"""The four seams between lanes.

These Protocols are the contract. A lane depends on the Protocol, never on
another lane's concrete class — that is what lets five instances build
simultaneously and wire together at the end.

The docstrings here are the specification. If behaviour isn't stated here,
the implementing lane decides it and documents it in its own README.

FROZEN after Wave 0. Need a change? File a request in docs/active-work.md.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import (
    AllocationDecision,
    ExecutionPlan,
    Fact,
    Mandate,
    MarketSnapshot,
    VaultState,
    VenueIntent,
)

# ── DataSource (implemented by Lane C, consumed by Lane B) ────────────────


@runtime_checkable
class DataSource(Protocol):
    """One provider of market facts.

    Implementations contribute a PARTIAL view and know nothing about each
    other. The registry merges contributions into a single MarketSnapshot.
    That is deliberate: it is what makes adding Chainlink, Pyth or DefiLlama
    later a matter of writing one file and adding one registration line.

    Contract:
      - `fetch` returns whatever facts this source can supply. Returning an
        empty list is legal and means "nothing to say", not an error.
      - `fetch` MUST NOT raise for expected failures (timeout, rate limit,
        missing market). Raise only for programmer error. The registry catches
        exceptions and records them in MarketSnapshot.errors so a dead source
        degrades the snapshot instead of killing the decision loop.
      - Every Fact must carry `source=self.key` so provenance survives the
        merge and the UI can show where a number came from.
      - Values must be normalized to the declared unit at this boundary
        (apy_fraction is 0.0432 for 4.32%, never 4.32).
    """

    #: Registry key. This is what a Mandate names in permitted_data_sources,
    #: so it is user-visible and effectively permanent once shipped.
    key: str

    async def fetch(self, assets: list[str]) -> list[Fact]:
        """Facts relevant to `assets` (symbols from the mandate)."""
        ...


@runtime_checkable
class DataSourceRegistry(Protocol):
    """Resolves mandate source keys to providers and merges their output.

    The mandate's `permitted_data_sources` list IS the access-control
    mechanism: a source not named there is never consulted. This is exactly
    the "user selects which data sources the agent may consult" flow from
    plans/initiate_plan.md §3.1 — same mechanism, no separate concept.
    """

    def available(self) -> list[str]:
        """Registered keys. The genesis UI offers these to the user."""
        ...

    async def snapshot(self, source_keys: list[str], assets: list[str]) -> MarketSnapshot:
        """Fan out to the named sources concurrently and merge.

        Unknown keys and failing sources land in MarketSnapshot.errors rather
        than raising.
        """
        ...


# ── ModelBackend (implemented by Lane B) ──────────────────────────────────


@runtime_checkable
class ModelBackend(Protocol):
    """An OpenAI-compatible chat completion endpoint.

    Standardizing on this shape means Ollama and vLLM work behind one
    interface today, and a hosted provider is a drop-in later without
    touching the decision loop.
    """

    name: str

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Raw model text.

        `json_schema` is a hint the backend may pass through as structured-output
        or grammar constraints. It is NOT a guarantee — callers must still
        validate. Small open models produce malformed structured output
        regularly, and the agent holds a key, so validation is the harness's
        job and cannot be delegated to the backend.
        """
        ...


# ── Venue (implemented by Lane D, consumed by Lane B) ─────────────────────


@runtime_checkable
class Venue(Protocol):
    """Turns a venue intent into concrete transactions.

    Implementations build calldata off-chain and never touch contracts/. The
    vault executes opaque calldata against an allowlisted target, so a new
    venue is a new adapter rather than a contract change.
    """

    #: Registry key, named in Mandate.permitted_venues.
    key: str

    async def plan(self, intent: VenueIntent, vault: VaultState) -> ExecutionPlan:
        """Build the transaction sequence for `intent`.

        Contract:
          - Every `step.target` must be on the vault's allowlist, or execute()
            reverts. Coordinate the allowlist with Lane A at CP1.
          - Order matters: emit approvals before the calls that need them.
          - Populate `expected_slippage_bps` where the venue can estimate it;
            the harness rejects plans exceeding the mandate's ceiling.
          - Set `quote_expires_at` when the plan embeds a router quote —
            stale quotes must not be submitted.
        """
        ...


# ── VaultClient (implemented by Lane B over Lane A's ABIs) ────────────────


@runtime_checkable
class VaultClient(Protocol):
    """Chain access for one vault.

    Invariant callers may rely on: the vault is sole custodian. Capital never
    leaves it, so VaultState.holdings is the complete position picture even
    while Aqua strategies are open.
    """

    async def state(self, vault: str) -> VaultState:
        """Current on-chain state."""
        ...

    async def execute(self, vault: str, plan: ExecutionPlan) -> list[str]:
        """Submit each step via the vault's agent-only execute(). Returns tx
        hashes in order. Raises if any step reverts — a partially-applied plan
        is a real outcome the caller must record on the AgentAction."""
        ...

    async def deploy(self, mandate: Mandate, mandate_hash: str) -> tuple[str, str]:
        """Clone a new vault via the factory. Returns (vault_address, tx_hash)."""
        ...


# ── DecisionEngine (Lane B internal; stated here so Lane E can mock it) ───


@runtime_checkable
class DecisionEngine(Protocol):
    """Snapshot + mandate in, validated decision out.

    Implementations MUST validate model output against AllocationDecision and
    against the mandate's constraints (allowed assets, weight sum, slippage
    ceiling) before returning, retrying with the validation error fed back
    into the prompt. Nothing unvalidated reaches a Venue.
    """

    async def decide(self, mandate: Mandate, snapshot: MarketSnapshot) -> AllocationDecision:
        ...


__all__ = [
    "DataSource",
    "DataSourceRegistry",
    "ModelBackend",
    "Venue",
    "VaultClient",
    "DecisionEngine",
]
