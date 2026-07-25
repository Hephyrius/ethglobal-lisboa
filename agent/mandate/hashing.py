"""Canonical mandate serialization and its keccak256 hash.

`mandate_hash` is recorded on-chain at genesis so a depositor can verify that the
mandate they were shown in the dApp is the one the vault was actually deployed
against (`VaultState.mandate_hash`, `VaultCreated(…, mandateHash)`). That check
only means anything if independent implementations agree byte-for-byte on how a
mandate serializes — so canonicalization is defined here, once, and both fixture
mode and live mode use it. Same mandate in, same hash out, on any machine.

Canonical form: UTF-8 JSON, keys sorted, no insignificant whitespace, unset
optional fields omitted, datetimes as RFC 3339 UTC with a `Z` suffix.

## Schema evolution moves the hash, and that is the correct behaviour

Lane F measured this when Wave 2 added `MandateConstraints.tolerance_band_pct`
with a default of `0.05` (request #71): a vault deployed before the delta stopped
reproducing its on-chain hash, because the field materializes when the stored
JSON is parsed and then appears in the canonical form. Any future non-`None`
default does the same.

The tempting fix is to hash the stored bytes so the digest survives schema
changes. **This module deliberately does not**, for two reasons.

The first is that it would not work here. What `MandateStore` writes is already a
re-serialization, and `GET /vault/{addr}/mandate` returns another one — a
depositor is never handed "the bytes", so hashing bytes nobody can obtain moves
verification from *wrong* to *impossible*. Making the preimage retrievable is a
different and larger change than the one being asked for.

The second is the real one: **the mismatch is a true statement.** A vault
deployed before the delta is now curated by a harness that will accept a decision
5% over `max_position_pct` — on a mandate whose depositors were promised a hard
cap. The effective mandate genuinely changed. A digest engineered to keep
matching would be an on-chain claim that nothing had, which is precisely the
claim the hash exists to make falsifiable.

So the hash stays honest and the *mismatch* is made legible instead:
`verify_mandate_hash` separates the three reasons a recompute can differ, only
one of which is alarming. See `HashVerification.explain`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from curator_schema import Mandate
from eth_utils import keccak

__all__ = [
    "FieldDrift",
    "HashVerification",
    "canonical_json",
    "mandate_hash",
    "schema_drift",
    "verify_mandate_hash",
]


def canonical_json(mandate: Mandate) -> str:
    """Deterministic JSON for hashing.

    `exclude_none` drops unset optionals rather than emitting nulls, so a
    mandate round-tripped through the API hashes identically to the one the user
    approved — adding an explicit `"update_rules": null` must not change the
    hash of a mandate that simply has no update rules.
    """
    payload = json.loads(mandate.model_dump_json(exclude_none=True))
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def mandate_hash(mandate: Mandate) -> str:
    """keccak256 of the canonical form, as a 0x-prefixed bytes32 string."""
    return "0x" + keccak(text=canonical_json(mandate)).hex()


@dataclass(frozen=True)
class FieldDrift:
    """One field the current schema applies that the stored mandate does not say.

    `absent` is the distinction that matters. A field the stored mandate never
    mentioned is a constraint the depositor never agreed to; a field whose value
    *changed* would mean the file was edited, which nothing in this system is
    permitted to do outside `agent/mandate/amend.py`.
    """

    path: str
    stored: Any | None
    effective: Any | None
    absent: bool

    def __str__(self) -> str:
        if self.absent:
            return (
                f"{self.path} is not in the stored mandate; "
                f"the harness applies {self.effective!r}"
            )
        if self.effective is None:
            return f"{self.path} was {self.stored!r} and the current schema drops it"
        return f"{self.path} is stored as {self.stored!r} but applied as {self.effective!r}"


def _walk(stored: Any, effective: Any, path: str) -> list[FieldDrift]:
    if isinstance(stored, dict) and isinstance(effective, dict):
        drift: list[FieldDrift] = []
        for key in sorted(set(stored) | set(effective)):
            here = f"{path}.{key}" if path else key
            if key not in stored:
                drift.extend(_walk(_MISSING, effective[key], here))
            elif key not in effective:
                drift.append(FieldDrift(here, stored[key], None, absent=False))
            else:
                drift.extend(_walk(stored[key], effective[key], here))
        return drift

    if stored is _MISSING:
        # A whole object arriving at once is reported leaf by leaf, so the
        # explanation names constraints rather than "constraints changed".
        if isinstance(effective, dict):
            return [
                drift
                for key in sorted(effective)
                for drift in _walk(_MISSING, effective[key], f"{path}.{key}")
            ]
        return [FieldDrift(path, None, effective, absent=True)]

    # Lists compare whole: a reordered allowlist is one fact, not five.
    return [] if stored == effective else [FieldDrift(path, stored, effective, absent=False)]


#: Distinguishes "absent from the stored mandate" from "stored as null".
_MISSING = object()


def schema_drift(stored_json: str, mandate: Mandate) -> tuple[FieldDrift, ...]:
    """What the current schema adds to, or changes about, the mandate on disk.

    Compares the bytes `MandateStore` wrote against the canonical form of the
    same file parsed under today's models. An empty result means the stored
    mandate and the running harness agree completely, and therefore that any hash
    mismatch has some other cause.
    """
    try:
        stored = json.loads(stored_json)
    except ValueError:
        return ()
    return tuple(_walk(stored, json.loads(canonical_json(mandate)), ""))


@dataclass(frozen=True)
class HashVerification:
    """Why a recomputed mandate hash does or does not match the chain."""

    on_chain: str | None
    recomputed: str
    drift: tuple[FieldDrift, ...]
    #: Genesis binds the hash to version 1. The agent may amend afterwards.
    version: int

    @property
    def matches(self) -> bool:
        return self.on_chain is not None and self.on_chain.lower() == self.recomputed.lower()

    @property
    def amended(self) -> bool:
        return self.version > 1

    def explain(self) -> str:
        """One sentence a depositor can act on.

        Three causes, and only the last is alarming — which is the whole point of
        separating them. A judge who recomputes an older vault's hash and gets a
        mismatch should be able to tell "this predates a schema field" from "the
        mandate this vault claims to follow is not the one it was deployed with".
        """
        if self.matches:
            return (
                "The mandate this vault serves hashes to the value recorded on-chain at "
                "genesis. It has not changed since deployment."
            )
        if self.on_chain is None:
            return (
                "This vault reports no mandate hash on-chain, so there is nothing to verify "
                "against. It was deployed by something other than this factory."
            )
        if self.amended:
            return (
                f"This mandate is version {self.version} — the agent has amended it since "
                "genesis, and the on-chain hash binds version 1. A mismatch is expected; the "
                "amendment history is in the decision feed."
            )
        if self.drift:
            fields = ", ".join(d.path for d in self.drift if d.absent) or "fields"
            return (
                f"This vault predates part of the current schema, and the harness is applying "
                f"{fields}, which its stored mandate does not mention. The hash therefore no "
                "longer matches — correctly, because the rules the vault is run under are no "
                "longer exactly the rules it was deployed with."
            )
        return (
            "The stored mandate does not hash to the value recorded on-chain, and no schema "
            "difference or amendment explains it. Treat this vault's stated mandate as "
            "unverified."
        )


def verify_mandate_hash(
    stored_json: str, mandate: Mandate, on_chain: str | None
) -> HashVerification:
    """Recompute the hash and account for any difference from the chain."""
    return HashVerification(
        on_chain=on_chain,
        recomputed=mandate_hash(mandate),
        drift=schema_drift(stored_json, mandate),
        version=mandate.version,
    )
