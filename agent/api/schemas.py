"""Request and response bodies for the frozen API contract.

Mirrors the zod definitions at the bottom of `packages/schema/ts/src/index.ts`.
The domain shapes (`Mandate`, `VaultState`, `AgentAction`, …) are imported from
`curator_schema` rather than redeclared — only the request/response envelopes
live here.

Two wire-format rules are enforced by construction, both because zod is stricter
than pydantic is by default:

1. **`extra="forbid"`** everywhere, matching zod's `.strict()`.
2. **Optional fields are omitted, never null.** zod's `.optional()` accepts
   `undefined` but rejects `null`, so a pydantic default of `None` serialized as
   `null` fails in the browser while passing every Python test. Routes set
   `response_model_exclude_none=True`; fields that are genuinely nullable in the
   contract (`AgentAction.error`, `Holding.committed_to_venue`) declare
   `.nullable().default(null)` on the zod side and so survive omission.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from curator_schema import Mandate, MandateConstraints
from curator_schema.models import Address, Bytes32
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ArchetypeDeployRequest",
    "ArchetypeDeployResponse",
    "ArchetypeSummary",
    "ChatMessage",
    "GenesisChatRequest",
    "GenesisChatResponse",
    "GenesisFinalizeRequest",
    "GenesisFinalizeResponse",
    "MandateDraft",
    "SourcesResponse",
    "HealthResponse",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatMessage(Strict):
    role: Literal["user", "assistant"]
    content: str


class GenesisChatRequest(Strict):
    messages: list[ChatMessage]


class MandateDraft(Strict):
    """`Mandate.partial()` — the shallow partial zod produces.

    A draft is what the model has pinned down *so far* during the genesis
    conversation. Every field is optional because early turns legitimately know
    almost nothing; `constraints`, if present at all, must be complete, exactly
    as zod's shallow `.partial()` requires.
    """

    version: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    objective: str | None = Field(default=None, min_length=1, max_length=2000)
    base_asset: str | None = None
    constraints: MandateConstraints | None = None
    permitted_data_sources: list[str] | None = None
    permitted_venues: list[Literal["uniswap", "aqua"]] | None = None
    created_at: datetime | None = None
    risk_posture: Literal["conservative", "balanced", "aggressive"] | None = None
    update_rules: str | None = Field(default=None, max_length=1000)


class GenesisChatResponse(Strict):
    reply: str
    mandate_draft: MandateDraft | None = None


class GenesisFinalizeRequest(Strict):
    mandate: Mandate


class GenesisFinalizeResponse(Strict):
    mandate_hash: Bytes32
    deploy_tx: Bytes32
    vault: Address


class SourcesResponse(Strict):
    """Registry keys the genesis UI offers the user.

    Not one of the five frozen routes. It exists so the "user selects which data
    sources the agent may consult" step renders whatever Lane C has actually
    registered, rather than a list hardcoded in the dApp that silently rots the
    moment a source is added or renamed.
    """

    sources: list[str]
    venues: list[str]


class FieldDrift(Strict):
    """One field the running harness applies that the stored mandate omits."""

    path: str
    absent: bool
    stored: Any | None = None
    effective: Any | None = None
    #: The same fact as a sentence, so the dApp can render it without knowing
    #: which of the three shapes above apply.
    detail: str


class MandateVerificationResponse(Strict):
    """Whether this vault's mandate still hashes to what the chain recorded.

    Exists because the answer stopped being a plain yes/no when the schema
    gained a defaulted field (cross-lane #71). A mismatch has three possible
    causes and only one is alarming, so the response separates them rather than
    returning a boolean a reader would have to interpret.
    """

    vault: str
    recomputed: str
    matches: bool
    #: The agent amends mandates; genesis binds the hash to version 1. A version
    #: above 1 is an expected mismatch, not a failed verification.
    version: int
    amended: bool
    drift: list[FieldDrift]
    explanation: str
    on_chain: str | None = None


class ArchetypeDeployRequest(Strict):
    """Everything a card click carries, which is deliberately almost nothing.

    No mandate, no draft, no preferences: an archetype is generated, not
    configured (§4 B1, *"no user input beyond the archetype key and the deployer
    address"*). A field here would be a field someone has to be shown, and the
    feature is one button.
    """

    #: The wallet that clicked. Optional so the route works before a wallet is
    #: connected, and **asserted rather than proven** — the agent submits the
    #: transaction, so this records who asked, exactly as Lane A's on-chain
    #: `deployer` does (§A1). Never treat it as a signature.
    deployer: Address | None = None


class ArchetypeDeployResponse(Strict):
    """A vault nobody wrote, on-chain.

    Extends the genesis finalize shape rather than replacing it, because that is
    the honest description: this *is* a genesis, with the model in the seat the
    human normally occupies.
    """

    vault: Address
    mandate_hash: Bytes32
    deploy_tx: Bytes32
    archetype: str
    #: The generated mandate itself, returned so the dApp can render what it just
    #: deployed without a second round trip — nothing else has ever seen it.
    mandate: Mandate
    #: Which of the archetype's angles produced this one. The most legible piece
    #: of evidence that two clicks are not the same click.
    emphasis: str
    #: Generations it took, including the successful one. Above 1 means the
    #: envelope check rejected something and it never deployed.
    attempts: int = 1
    #: The rejections, in the words the model was given back.
    rejections: list[str] = Field(default_factory=list)
    #: True when this strategy matched one this archetype already deployed and
    #: the attempts ran out. Inside its bounds, just not new.
    collided: bool = False


class ArchetypeSummary(Strict):
    """One card's worth of an envelope, flattened for the dApp.

    Bounds are passed through as they are declared rather than prose-described
    here: Lane E has the same JSON and a describer generated from it, so a
    sentence written in this lane would be a second place for the card's promise
    to drift from the rule that enforces it.
    """

    key: str
    name: str
    headline: str
    tradeoff: str
    base_asset: str
    allowed_assets: list[str]
    permitted_venues: list[str]
    risk_postures: list[str]
    constraint_ranges: dict[str, dict[str, float]]
    #: How many vaults this archetype has already produced in this deployment.
    deployed: int = 0


class HealthResponse(Strict):
    status: Literal["ok", "degraded"]
    mode: Literal["fixture", "live"]
    #: Which provider each seam resolved to — "fixture" or the configured
    #: "module:attribute" ref. The fastest way to see why a live run is serving
    #: fixture numbers.
    data_registry: str
    venue_registry: str
    model_backend: str
    model_reachable: bool | None = None
