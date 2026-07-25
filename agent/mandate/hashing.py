"""Canonical mandate serialization and its keccak256 hash.

`mandate_hash` is recorded on-chain at genesis so a depositor can verify that the
mandate they were shown in the dApp is the one the vault was actually deployed
against (`VaultState.mandate_hash`, `VaultCreated(…, mandateHash)`). That check
only means anything if independent implementations agree byte-for-byte on how a
mandate serializes — so canonicalization is defined here, once, and both fixture
mode and live mode use it. Same mandate in, same hash out, on any machine.

Canonical form: UTF-8 JSON, keys sorted, no insignificant whitespace, unset
optional fields omitted, datetimes as RFC 3339 UTC with a `Z` suffix.
"""

from __future__ import annotations

import json

from curator_schema import Mandate
from eth_utils import keccak

__all__ = ["canonical_json", "mandate_hash"]


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
