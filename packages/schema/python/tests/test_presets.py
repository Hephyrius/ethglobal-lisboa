"""Presets must be deployable mandates, not illustrations of one.

`packages/schema/presets/*.json` is offered two ways: Lane B reads it in the
genesis conversation and Lane E renders it as a click-to-load card. Both paths
end in `POST /genesis/finalize`, which deploys a real vault — so a preset that
does not validate, or that validates while contradicting itself, is a button
that fails in front of a judge.

This test is the reason §3.3 of the Wave 2 plan says a preset can never be
un-deployable. It checks four things the `Mandate` schema alone cannot:

1. every preset validates against BOTH the JSON Schema and the pydantic mirror;
2. the index and the directory agree exactly, in both directions;
3. the cross-field invariants a hand-written mandate gets wrong;
4. every venue named has an adapter, and every constraint is internally
   satisfiable.

Run:  uv run pytest packages/schema/python -q
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from curator_schema import Mandate
from schema_registry import PRESET_DIR, SCHEMA_DIR, errors_against

INDEX = PRESET_DIR / "index.json"

#: Venue keys with a built adapter. Mirrors the closed Literal on
#: `Mandate.permitted_venues` — a preset naming a venue with no adapter produces
#: a vault whose agent proposes trades the harness can only ever reject.
VENUES_WITH_ADAPTERS = {"uniswap", "aqua", "aave"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _preset_files() -> list[Path]:
    return sorted(p for p in PRESET_DIR.glob("*.json") if p.name != "index.json")


def _keys() -> list[str]:
    return [p.stem for p in _preset_files()]


def test_index_validates() -> None:
    errors = errors_against("preset-index.schema.json", _load(INDEX))
    assert not errors, errors


def test_index_and_directory_agree() -> None:
    """Both directions on purpose.

    A listed-but-missing preset is a card that 404s. A present-but-unlisted one
    is worse in a quieter way: it exists, looks maintained, and is never offered
    to anybody, which is exactly how the fully-built Aave venue stayed
    ungrantable for a whole wave.
    """
    indexed = {e["key"] for e in _load(INDEX)["presets"]}
    on_disk = set(_keys())
    assert indexed == on_disk, f"index/directory mismatch: {indexed ^ on_disk}"


def test_index_paths_resolve() -> None:
    for entry in _load(INDEX)["presets"]:
        path = SCHEMA_DIR / entry["file"]
        assert path.is_file(), f"{entry['key']}: {entry['file']} does not exist"
        assert path.stem == entry["key"], f"{entry['key']}: file stem must equal key"


@pytest.mark.parametrize("key", _keys())
def test_preset_matches_json_schema(key: str) -> None:
    errors = errors_against("mandate.schema.json", _load(PRESET_DIR / f"{key}.json"))
    assert not errors, errors


@pytest.mark.parametrize("key", _keys())
def test_preset_matches_pydantic(key: str) -> None:
    Mandate.model_validate(_load(PRESET_DIR / f"{key}.json"))


@pytest.mark.parametrize("key", _keys())
def test_preset_roundtrip_is_stable(key: str) -> None:
    """A preset that pydantic accepts but re-emits in a shape the JSON Schema
    rejects would break the moment the API echoed it back."""
    mandate = Mandate.model_validate(_load(PRESET_DIR / f"{key}.json"))
    emitted = json.loads(mandate.model_dump_json(exclude_none=True))
    errors = errors_against("mandate.schema.json", emitted)
    assert not errors, errors


@pytest.mark.parametrize("key", _keys())
def test_base_asset_is_holdable(key: str) -> None:
    """`allowed_assets` must include `base_asset`, or the vault may not hold the
    asset it does its own accounting in."""
    mandate = Mandate.model_validate(_load(PRESET_DIR / f"{key}.json"))
    assert mandate.base_asset in mandate.constraints.allowed_assets


@pytest.mark.parametrize("key", _keys())
def test_position_cap_and_cash_floor_leave_room(key: str) -> None:
    """A cap reachable only by breaching the floor advertises headroom the
    mandate does not actually have, and the agent would spend every tick being
    rejected by one of its own two constraints.

    Only checked when there IS a non-base asset. `max_position_pct` is a ceiling
    on any single **non-base** asset, so a lending-only mandate that permits its
    base asset and nothing else can leave it at the default 1.0 without
    contradicting anything — there is no position for it to bind on. This
    distinction is not pedantic: it is the difference between a preset with an
    unsatisfiable pair of rules and one where a rule is simply inapplicable.
    """
    mandate = Mandate.model_validate(_load(PRESET_DIR / f"{key}.json"))
    c = mandate.constraints
    if set(c.allowed_assets) <= {mandate.base_asset}:
        return
    assert c.max_position_pct + c.min_cash_pct <= 1.0, (
        f"{key}: max_position_pct {c.max_position_pct} + min_cash_pct "
        f"{c.min_cash_pct} exceeds the whole book"
    )


@pytest.mark.parametrize("key", _keys())
def test_every_venue_has_an_adapter(key: str) -> None:
    mandate = Mandate.model_validate(_load(PRESET_DIR / f"{key}.json"))
    unknown = set(mandate.permitted_venues) - VENUES_WITH_ADAPTERS
    assert not unknown, f"{key}: no adapter for {unknown}"


@pytest.mark.parametrize("key", _keys())
def test_a_venue_exists_for_the_assets_held(key: str) -> None:
    """A mandate allowing two assets with no swap venue can never reach its own
    target allocation: it could accept a deposit in the base asset and would
    have no way to acquire the other one."""
    mandate = Mandate.model_validate(_load(PRESET_DIR / f"{key}.json"))
    if len(mandate.constraints.allowed_assets) > 1:
        assert "uniswap" in mandate.permitted_venues, (
            f"{key}: allows {mandate.constraints.allowed_assets} but grants no swap venue"
        )


@pytest.mark.parametrize("key", _keys())
def test_capital_can_be_deployed(key: str) -> None:
    """The Wave 2 headline is that idle capital gets deployed. A preset that
    grants no venue capable of earning on the base asset makes that impossible
    by construction, whatever the objective says."""
    mandate = Mandate.model_validate(_load(PRESET_DIR / f"{key}.json"))
    earning = {"aave", "aqua"} & set(mandate.permitted_venues)
    assert earning, f"{key}: no venue that can earn on idle capital"


@pytest.mark.parametrize("key", _keys())
def test_objective_states_what_to_do_with_idle_capital(key: str) -> None:
    """Cheap and it caught a real gap while these were being written: the
    genesis conversation reads the objective aloud, and the idle-capital default
    has to be in the mandate the user agreed to, not only in the harness prompt
    that happens to be running."""
    mandate = Mandate.model_validate(_load(PRESET_DIR / f"{key}.json"))
    text = mandate.objective.lower()
    assert any(w in text for w in ("idle", "sitting", "deployed", "put to work", "unlent")), (
        f"{key}: objective says nothing about idle capital"
    )


@pytest.mark.parametrize("key", _keys())
def test_persona_never_widens_a_constraint(key: str) -> None:
    """Structural half of the invariant Lane B pins behaviourally.

    A persona is taste; constraints are law. It cannot widen anything if it
    carries no numbers and names no asset — so assert that shape here, where a
    persona is authored, rather than only downstream where it is consumed.
    """
    mandate = Mandate.model_validate(_load(PRESET_DIR / f"{key}.json"))
    if mandate.persona is None:
        return
    allowed = {a.lower() for a in mandate.constraints.allowed_assets}
    for text in [mandate.persona.voice, *mandate.persona.biases]:
        words = {w.strip(".,;:()'\"").lower() for w in text.split()}
        assert not (words & ({"usdc", "weth", "cbbtc", "wsteth", "eth"} - allowed)), (
            f"{key}: persona names an asset outside allowed_assets: {text!r}"
        )
        assert "%" not in text, (
            f"{key}: persona carries a percentage, which reads as a bound: {text!r}"
        )


def test_presets_differ_where_it_matters() -> None:
    """Three presets that differ only in wording are one preset with three
    names. The user is choosing between risk shapes, so the numbers must differ.
    """
    shapes = {
        key: (
            Mandate.model_validate(_load(PRESET_DIR / f"{key}.json")).constraints.min_cash_pct,
            Mandate.model_validate(_load(PRESET_DIR / f"{key}.json")).constraints.max_slippage_bps,
        )
        for key in _keys()
    }
    assert len(set(shapes.values())) == len(shapes), f"presets are not distinct: {shapes}"


def test_at_least_two_personas_and_one_neutral() -> None:
    """The Wave 2 definition of done needs two visibly different personas
    deciding from the same snapshot, and a neutral mandate is the control that
    shows the difference came from the persona rather than from the snapshot.
    """
    personas = [
        Mandate.model_validate(_load(p)).persona for p in _preset_files()
    ]
    assert sum(p is not None for p in personas) >= 2, "need two personas to contrast"
    assert any(p is None for p in personas), "need one neutral preset as the control"
    named = [p.name for p in personas if p is not None]
    assert len(set(named)) == len(named), "persona names must be distinct"
