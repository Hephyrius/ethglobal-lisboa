"""Mandate hashing and agent-side amendment.

`mandate_hash` is the depositor's only way to check that the mandate they were
shown in the dApp is the one the vault was actually deployed against. That check
is worth exactly as much as the canonicalization is stable — if two equivalent
representations of the same mandate hash differently, the verification is
theatre. So the properties are asserted rather than assumed: key order,
null-versus-absent, and unicode must not move the hash, and any change of
substance must.

Amendment is tested here too because it is the one path that rewrites a live
mandate, and the invariants it enforces are the ones free-text `update_rules`
cannot.
"""

from __future__ import annotations

import json

import pytest
from curator_schema import Mandate, MandateAmendment

from agent import fixtures
from agent.mandate.amend import AmendmentRejected, apply_amendment
from agent.mandate.hashing import canonical_json, mandate_hash
from agent.mandate.store import MandateNotFound, MandateStore

VAULT = "0x1111111111111111111111111111111111111111"


@pytest.fixture
def mandate() -> Mandate:
    return fixtures.mandate()


# ── the hash must be stable across equivalent representations ─────────────


def test_the_same_mandate_always_hashes_the_same(mandate):
    assert mandate_hash(mandate) == mandate_hash(mandate)


def test_key_order_in_the_source_json_does_not_move_the_hash(mandate):
    """The dApp, the API and the store may serialize fields in any order."""
    payload = json.loads(mandate.model_dump_json(exclude_none=True))
    reversed_keys = dict(reversed(list(payload.items())))
    assert mandate_hash(Mandate.model_validate(reversed_keys)) == mandate_hash(mandate)


def test_an_explicit_null_hashes_the_same_as_an_absent_field():
    """Claimed in `hashing.py`, so it had better be true.

    A mandate with no update rules must hash identically whether the field is
    omitted or sent as null — otherwise a round trip through a client that
    serializes nulls silently invalidates the on-chain commitment.
    """
    base = json.loads(fixtures.mandate().model_dump_json(exclude_none=True))
    base.pop("update_rules", None)

    without = Mandate.model_validate(base)
    with_null = Mandate.model_validate({**base, "update_rules": None})

    assert mandate_hash(without) == mandate_hash(with_null)


def test_unicode_survives_canonicalization(mandate):
    """`ensure_ascii=False` means the objective is hashed as real UTF-8."""
    accented = mandate.model_copy(update={"objective": "Preserve capital — no drawdown ≥5%."})
    canonical = canonical_json(accented)
    assert "—" in canonical and "≥" in canonical
    assert mandate_hash(accented) == mandate_hash(accented.model_copy())


def test_canonical_form_is_sorted_and_tightly_separated(mandate):
    """Structural separators carry no whitespace and keys are sorted.

    Asserted by re-canonicalizing rather than by substring search: `", "` occurs
    legitimately inside the objective prose, so looking for it finds the mandate
    text rather than a formatting defect.
    """
    canonical = canonical_json(mandate)
    parsed = json.loads(canonical)

    assert canonical == json.dumps(
        parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert list(parsed) == sorted(parsed), "top-level keys must be sorted"
    assert canonical.startswith('{"') and canonical.endswith("}")


def test_the_hash_is_a_bytes32_hex_string(mandate):
    digest = mandate_hash(mandate)
    assert digest.startswith("0x") and len(digest) == 66
    int(digest, 16)


# ── ...and must move when anything of substance changes ───────────────────


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("objective", "Chase the highest APY available at any risk."),
        ("base_asset", "WETH"),
        ("risk_posture", "aggressive"),
        ("permitted_data_sources", ["messari"]),
        ("permitted_venues", ["uniswap"]),
        ("version", 2),
        ("name", "Something Else"),
    ],
)
def test_a_material_change_changes_the_hash(mandate, field, value):
    """Otherwise the on-chain commitment proves nothing about which mandate ran."""
    assert mandate_hash(mandate.model_copy(update={field: value})) != mandate_hash(mandate)


def test_changing_a_single_constraint_changes_the_hash(mandate):
    relaxed = mandate.constraints.model_copy(update={"min_cash_pct": 0.0})
    assert mandate_hash(mandate.model_copy(update={"constraints": relaxed})) != mandate_hash(
        mandate
    )


# ── persistence ───────────────────────────────────────────────────────────


def test_a_mandate_round_trips_through_the_store(tmp_path, mandate):
    store = MandateStore(tmp_path)
    digest = store.save(VAULT, mandate)

    loaded = store.load(VAULT)
    assert loaded == mandate
    assert mandate_hash(loaded) == digest, "persistence must not perturb the hash"


def test_loading_an_unknown_vault_raises_a_named_error(tmp_path):
    with pytest.raises(MandateNotFound):
        MandateStore(tmp_path).load(VAULT)


def test_a_checksummed_address_finds_a_lowercase_file(tmp_path, mandate):
    """Addresses are case-insensitive on-chain, case-sensitive on disk."""
    store = MandateStore(tmp_path)
    store.save(VAULT.lower(), mandate)
    assert store.load(VAULT.upper().replace("0X", "0x")) == mandate


def test_saving_twice_leaves_no_temporary_file(tmp_path, mandate):
    """Writes are atomic via os.replace; a stray .tmp means one did not complete."""
    store = MandateStore(tmp_path)
    store.save(VAULT, mandate)
    store.save(VAULT, mandate.model_copy(update={"version": 2}))

    assert list((tmp_path / "mandates").glob("*.tmp")) == []
    assert store.load(VAULT).version == 2


# ── amendment: the invariants free text cannot enforce ────────────────────


def _amend(**patch) -> MandateAmendment:
    return MandateAmendment(rationale="because the market moved", patch=patch)


def test_a_valid_amendment_increments_the_version(mandate):
    updated = apply_amendment(mandate, _amend(risk_posture="balanced"))
    assert updated.version == mandate.version + 1
    assert updated.risk_posture == "balanced"


def test_the_model_cannot_choose_its_own_version(mandate):
    """Version is the audit trail's ordering key; left to the model it collides."""
    updated = apply_amendment(mandate, _amend(version=99, risk_posture="balanced"))
    assert updated.version == mandate.version + 1


def test_the_base_asset_can_never_change(mandate):
    """The ERC-4626 asset is fixed at deployment — a mandate naming another one
    is unexecutable, and every share-price figure would change meaning."""
    with pytest.raises(AmendmentRejected, match="base_asset"):
        apply_amendment(mandate, _amend(base_asset="WETH"))


def test_an_amendment_cannot_orphan_the_base_asset(mandate):
    """Dropping USDC from allowed_assets leaves the vault unable to hold its own
    denomination, and makes min_cash_pct unsatisfiable."""
    constraints = mandate.constraints.model_copy(update={"allowed_assets": ["WETH"]})
    with pytest.raises(AmendmentRejected, match="base asset"):
        apply_amendment(mandate, _amend(constraints=constraints.model_dump(mode="json")))


def test_an_unknown_field_is_refused(mandate):
    with pytest.raises(AmendmentRejected, match="unknown"):
        apply_amendment(mandate, _amend(leverage=3))


def test_an_empty_patch_is_refused(mandate):
    with pytest.raises(AmendmentRejected, match="empty"):
        apply_amendment(mandate, MandateAmendment(rationale="no change", patch={}))


def test_a_patch_producing_an_invalid_mandate_is_rejected_whole(mandate):
    """No partial application — the old mandate stands untouched."""
    with pytest.raises(AmendmentRejected, match="invalid"):
        apply_amendment(mandate, _amend(permitted_data_sources=[]))
    assert mandate.permitted_data_sources, "the original must be unmodified"


def test_amendment_changes_the_hash(mandate):
    """A depositor must be able to see that the mandate moved."""
    updated = apply_amendment(mandate, _amend(risk_posture="aggressive"))
    assert mandate_hash(updated) != mandate_hash(mandate)


# ── the asset the vault cannot price (cross-lane #65) ─────────────────────


def test_an_amendment_cannot_add_an_asset_the_vault_cannot_price():
    """**The one that fails silently and permanently.**

    Lane C reported that wstETH, cbETH and rETH now all have Chainlink Base
    feeds, which makes the golden mandate's `update_rules` — *"new assets if they
    have a Chainlink Base feed"* — literally true for them. But every LST feed on
    Base is 18-decimal and ETH-quoted, not the 8-decimal USD the vault assumes;
    read as USD, wstETH prices at $12,399,811,032. Lane C composes with ETH/USD
    in Python. `CuratedVault.totalAssets()` takes one feed per token and cannot.

    So a model could amend honestly, nothing downstream would object, the vault
    would buy an asset `totalAssets()` cannot see, and the share price would fall
    by the amount spent — with `priceFeed` registrations immutable after
    `initialize`, so only redeployment fixes it.
    """
    from curator_schema import MandateAmendment

    from agent.mandate.amend import AmendmentRejected, apply_amendment

    current = fixtures.mandate()
    widened = current.constraints.model_copy(
        update={"allowed_assets": [*current.constraints.allowed_assets, "wstETH"]}
    )

    with pytest.raises(AmendmentRejected, match="cannot price"):
        apply_amendment(
            current,
            MandateAmendment(
                rationale="wstETH has a Chainlink Base feed, so the update rules permit it.",
                patch={"constraints": widened.model_dump(mode="json", exclude_none=True)},
            ),
        )


def test_the_rejection_says_why_a_chainlink_feed_is_not_enough():
    """The message is the model's only correction signal, and "not allowed" would
    invite it to try again with the same reasoning."""
    from curator_schema import MandateAmendment

    from agent.mandate.amend import AmendmentRejected, apply_amendment

    current = fixtures.mandate()
    widened = current.constraints.model_copy(
        update={"allowed_assets": [*current.constraints.allowed_assets, "rETH"]}
    )

    with pytest.raises(AmendmentRejected) as caught:
        apply_amendment(
            current,
            MandateAmendment(
                rationale="Adding rETH.",
                patch={"constraints": widened.model_dump(mode="json", exclude_none=True)},
            ),
        )

    message = str(caught.value)
    assert "Chainlink Base feed is not sufficient" in message
    assert "cannot compose" in message
    assert "immutable" in message


def test_an_amendment_may_still_add_an_asset_the_venue_layer_resolves():
    """The guard must not freeze the universe. Lane D's token table is curated on
    exactly the basis this needs, so anything in it is fair game."""
    from curator_schema import MandateAmendment

    from agent.mandate.amend import apply_amendment
    from agent.mandate.universe import offerable_assets

    current = fixtures.mandate()
    candidates = [a for a in offerable_assets() if a not in current.constraints.allowed_assets]
    if not candidates:
        pytest.skip("the golden mandate already names every offerable asset")

    widened = current.constraints.model_copy(
        update={"allowed_assets": [*current.constraints.allowed_assets, candidates[0]]}
    )
    updated = apply_amendment(
        current,
        MandateAmendment(
            rationale=f"Adding {candidates[0]}, which the venue layer resolves.",
            patch={"constraints": widened.model_dump(mode="json", exclude_none=True)},
        ),
    )

    assert candidates[0] in updated.constraints.allowed_assets
    assert updated.version == current.version + 1


def test_an_asset_already_in_the_mandate_survives_an_unrelated_amendment():
    """Additions only. A vault deployed under an older universe must stay
    amendable, or one widening of the token table would strand it."""
    from curator_schema import MandateAmendment

    from agent.mandate.amend import apply_amendment

    legacy = fixtures.mandate()
    legacy = legacy.model_copy(
        update={
            "constraints": legacy.constraints.model_copy(
                update={"allowed_assets": [*legacy.constraints.allowed_assets, "wstETH"]}
            )
        }
    )

    updated = apply_amendment(
        legacy,
        MandateAmendment(rationale="Tightening the cash floor.", patch={"objective": "Steady."}),
    )

    assert "wstETH" in updated.constraints.allowed_assets
