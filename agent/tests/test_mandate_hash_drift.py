"""A mandate hash that stops matching, and why that is the correct answer (#71).

Lane F measured this when the Wave 2 delta added
`MandateConstraints.tolerance_band_pct = 0.05`: a vault deployed before the
delta stopped reproducing its on-chain hash. The field materializes when the
stored JSON is parsed, so it appears in the canonical form and moves the digest.
`Mandate.persona` does not do this — it defaults to `None` and drops out — so any
future field with a non-`None` default will do it again.

**The fix is deliberately not "make the hash immune to schema evolution."**
Two reasons, both load-bearing enough to be tested here rather than only argued
in a docstring.

The first is that hashing the stored bytes would not work in this system. What
`MandateStore` writes is already a re-serialization and `GET /vault/{addr}/mandate`
returns another, so a depositor is never handed the preimage — hashing bytes
nobody can obtain moves verification from wrong to impossible.

The second is that the mismatch is **true**. A vault deployed before the delta is
now curated by a harness that will accept a decision 5% over `max_position_pct`,
on a mandate whose depositors were promised a hard cap. A digest engineered to
keep matching would be an on-chain assertion that nothing had changed, which is
exactly the claim the hash exists to make falsifiable.

So the hash stays honest and the *mismatch* is made legible: three causes, only
one of which is alarming.
"""

from __future__ import annotations

import json

import pytest
from curator_schema import Mandate

from agent import fixtures
from agent.mandate.hashing import (
    canonical_json,
    mandate_hash,
    schema_drift,
    verify_mandate_hash,
)
from agent.mandate.store import MandateStore

VAULT = "0x0E2c0e50E67B96C9C401C94e111a3DBD00DEB5d1"
BAND = "constraints.tolerance_band_pct"


def _pre_delta(mandate: Mandate) -> tuple[str, str]:
    """The stored JSON and on-chain hash of a vault deployed before the delta.

    Reconstructed by removing the field from the canonical form, which is
    precisely what the pre-delta code would have written and hashed.
    """
    payload = json.loads(canonical_json(mandate))
    payload["constraints"].pop("tolerance_band_pct", None)
    stored = json.dumps(payload, indent=2)

    from eth_utils import keccak

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return stored, "0x" + keccak(text=canonical).hex()


@pytest.fixture
def mandate() -> Mandate:
    return fixtures.mandate()


# ── the measured failure, reproduced ──────────────────────────────────────


def test_a_defaulted_field_moves_the_hash_of_an_already_deployed_vault(mandate):
    """Lane F's finding, pinned. Not a regression test — a *statement* test: it
    fails if someone makes the hash immune, which would need a conversation."""
    stored, on_chain = _pre_delta(mandate)
    reparsed = Mandate.model_validate_json(stored)

    assert mandate_hash(reparsed) != on_chain
    assert reparsed.constraints.tolerance_band_pct == 0.05, (
        "the whole mechanism is that parsing materializes the default"
    )


def test_the_drift_names_the_field_and_says_it_was_absent(mandate):
    """"Absent" is the distinction that matters. A field the stored mandate never
    mentioned is a constraint the depositor never agreed to; a field whose
    *value* changed would mean the file was edited, which nothing outside
    `agent/mandate/amend.py` is permitted to do."""
    stored, _ = _pre_delta(mandate)
    drift = schema_drift(stored, Mandate.model_validate_json(stored))

    assert [d.path for d in drift] == [BAND]
    assert drift[0].absent
    assert drift[0].stored is None
    assert drift[0].effective == 0.05
    assert "harness applies 0.05" in str(drift[0])


def test_the_explanation_blames_the_schema_and_not_the_vault(mandate):
    """A judge who recomputes an older vault's hash gets a mismatch. Whether that
    reads as "broken claim" or "documented consequence" is this sentence."""
    stored, on_chain = _pre_delta(mandate)
    verified = verify_mandate_hash(stored, Mandate.model_validate_json(stored), on_chain)

    assert not verified.matches
    assert BAND in verified.explain()
    assert "predates part of the current schema" in verified.explain()
    assert "no longer exactly the rules it was deployed with" in verified.explain()


# ── the other two causes ──────────────────────────────────────────────────


def test_a_current_vault_verifies_cleanly(mandate, tmp_path):
    """Round-tripped through the real store, so the formatting the store writes
    (indent=2) is proven not to count as drift."""
    store = MandateStore(tmp_path)
    on_chain = store.save(VAULT, mandate)
    stored = store.load_raw(VAULT)

    assert stored is not None
    verified = verify_mandate_hash(stored, store.load(VAULT), on_chain)

    assert verified.matches
    assert verified.drift == ()
    assert "has not changed since deployment" in verified.explain()


def test_an_amended_mandate_explains_itself_before_blaming_the_schema(mandate, tmp_path):
    """The shared demo vault has *both* causes at once, and Lane F nearly
    attributed the amendment to their delta. Version is checked first because it
    is the specific answer: genesis binds the hash to version 1."""
    store = MandateStore(tmp_path)
    genesis_hash = store.save(VAULT, mandate)
    amended = mandate.model_copy(update={"version": 2})
    store.save(VAULT, amended)

    verified = verify_mandate_hash(store.load_raw(VAULT) or "", store.load(VAULT), genesis_hash)

    assert not verified.matches
    assert verified.amended
    assert "version 2" in verified.explain()
    assert "amended it since genesis" in verified.explain()


def test_an_unexplained_mismatch_is_the_alarming_one(mandate, tmp_path):
    """The case the other messages exist to be distinguishable from. No schema
    difference, no amendment, and the digest still does not match."""
    store = MandateStore(tmp_path)
    store.save(VAULT, mandate)

    verified = verify_mandate_hash(store.load_raw(VAULT) or "", store.load(VAULT), "0x" + "ab" * 32)

    assert not verified.matches
    assert verified.drift == ()
    assert not verified.amended
    assert "unverified" in verified.explain()


def test_a_vault_with_no_hash_on_chain_is_not_accused_of_anything(mandate):
    """`mandate_hash` is optional on `VaultState` — an older deployment may not
    expose it, and "cannot verify" is not "failed verification"."""
    verified = verify_mandate_hash(canonical_json(mandate), mandate, None)

    assert not verified.matches
    assert "nothing to verify against" in verified.explain()


# ── the boring guarantees ─────────────────────────────────────────────────


def test_formatting_alone_is_never_drift(mandate):
    """Whitespace and key order are what a canonical form exists to neutralize.
    If these registered as drift, every vault would report as schema-drifted."""
    payload = json.loads(canonical_json(mandate))
    reordered = json.dumps(dict(reversed(list(payload.items()))), indent=8)

    assert schema_drift(reordered, mandate) == ()


def test_unreadable_stored_bytes_report_no_drift_rather_than_raising(mandate):
    """This runs on the depositor-facing path. A corrupt file must degrade to
    "cannot explain the mismatch", which is already the alarming message."""
    assert schema_drift("{not json", mandate) == ()


def test_the_store_can_hand_back_exactly_what_it_wrote(mandate, tmp_path):
    """`load()` alone cannot answer the question — parsing is what adds the
    field."""
    store = MandateStore(tmp_path)
    store.save(VAULT, mandate)

    assert json.loads(store.load_raw(VAULT) or "") == json.loads(canonical_json(mandate))
    assert store.load_raw("0x" + "99" * 20) is None


# ── the route ─────────────────────────────────────────────────────────────


def test_the_verification_route_answers_for_the_golden_vault(client):
    body = client.get(f"/vault/{VAULT}/mandate/verification").json()

    assert body["matches"] is True
    assert body["drift"] == []
    assert body["version"] == 1
    assert body["amended"] is False
    assert body["recomputed"] == body["on_chain"]
    assert "has not changed since deployment" in body["explanation"]


def test_the_route_rejects_a_malformed_address(client):
    assert client.get("/vault/not-an-address/mandate/verification").status_code == 422


def test_the_route_emits_no_nulls(client):
    """zod's `.optional()` accepts a missing key and **rejects** an explicit
    null, so a null here would fail in Lane E's browser while passing every
    Python test."""
    body = client.get(f"/vault/{VAULT}/mandate/verification").text

    assert "null" not in body
