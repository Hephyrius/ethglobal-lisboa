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
from typing import Literal

from curator_schema import Mandate, MandateConstraints
from curator_schema.models import Address, Bytes32
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
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
