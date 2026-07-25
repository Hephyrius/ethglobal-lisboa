"""The archetype envelopes, and the gate that keeps a generation inside one.

Nobody reads a generated mandate before it deploys, so these tests are the whole
review process for every vault an archetype card will ever create.

Two rules for what belongs here. Everything is **structural** — no network, no
model, no chain — and everything asserts something that would still be true if
the envelopes were rewritten. The cross-check that every asset, venue and source
named in an envelope actually resolves in the running system lives in
`tests/e2e/`, because it needs the other lanes and `curator_schema` must stay
importable on its own.
"""

from __future__ import annotations

import json

import pytest
from curator_schema import Mandate, load_archetype, load_archetypes
from curator_schema.archetypes import (
    ARCHETYPE_DIR,
    Archetype,
    NumericRange,
    SetBound,
    check_envelope,
    numeric_constraint_names,
)
from pydantic import ValidationError
from schema_registry import SCHEMA_DIR, errors_against, load

ARCHETYPES = load_archetypes()


def _mandate_at(archetype: Archetype, corner: str) -> Mandate:
    """The mandate sitting at one extreme corner of an envelope.

    `corner` is "min" or "max". Sets are taken at `min_count` (must_include
    first, then the subset in order) or at `max_count`; every numeric constraint
    is taken at that end of its range. These two mandates are the boundary of
    everything a generation may legally produce.
    """
    assert corner in ("min", "max")

    def pick(bound: SetBound) -> list[str]:
        ordered = list(bound.must_include) + [
            v for v in bound.subset_of if v not in bound.must_include
        ]
        ceiling = bound.max_count if bound.max_count is not None else len(bound.subset_of)
        return ordered[: bound.min_count if corner == "min" else ceiling]

    ranges = archetype.constraint_ranges
    constraints: dict[str, object] = {"allowed_assets": pick(archetype.allowed_assets)}
    for name in numeric_constraint_names():
        value = getattr(ranges[name], corner)
        # The mandate types these as int; a JSON range is read as float.
        constraints[name] = int(value) if name.endswith(("_bps", "_seconds", "_tick")) else value

    persona = None
    if archetype.persona is not None and archetype.persona.required:
        convictions = archetype.persona.conviction or ["medium"]
        persona = {
            "name": f"{archetype.name} corner",
            "voice": "Test fixture. Never rendered.",
            "conviction": convictions[0 if corner == "min" else -1],
        }

    return Mandate.model_validate(
        {
            "version": 1,
            "name": f"{archetype.name} at its {corner}",
            "objective": f"Corner case for {archetype.key}. Not a real strategy.",
            "base_asset": archetype.base_asset,
            "constraints": constraints,
            "permitted_data_sources": pick(archetype.permitted_data_sources),
            "permitted_venues": pick(archetype.permitted_venues),
            "risk_posture": archetype.risk_postures[0 if corner == "min" else -1],
            "persona": persona,
        }
    )


class TestTheCatalogue:
    def test_the_index_and_the_directory_agree_in_both_directions(self) -> None:
        """Listed-but-missing and present-but-unoffered are different bugs.

        Both are silent, and the second is the worse one: a file nobody listed is
        a deployable strategy nobody decided to offer.
        """
        index = load(ARCHETYPE_DIR / "index.json")
        listed = {entry["key"] for entry in index["archetypes"]}
        on_disk = {p.stem for p in ARCHETYPE_DIR.glob("*.json") if p.stem != "index"}
        assert listed == on_disk, f"listed-not-present {listed - on_disk}, present-not-listed {on_disk - listed}"

    def test_every_archetype_validates_against_its_json_schema(self) -> None:
        for entry in load(ARCHETYPE_DIR / "index.json")["archetypes"]:
            instance = load(SCHEMA_DIR / entry["file"])
            errors = errors_against("archetype.schema.json", instance)
            assert not errors, f"{entry['file']}:\n{errors}"

    def test_the_index_validates_against_its_own_schema(self) -> None:
        errors = errors_against("archetype-index.schema.json", load(ARCHETYPE_DIR / "index.json"))
        assert not errors, errors

    def test_the_pydantic_view_and_the_json_schema_do_not_disagree(self) -> None:
        """Both accept every shipped envelope. The JSON is the source of truth,
        so a disagreement means this module is the thing that is wrong."""
        for entry in load(ARCHETYPE_DIR / "index.json")["archetypes"]:
            raw = (SCHEMA_DIR / entry["file"]).read_text(encoding="utf-8")
            assert Archetype.model_validate_json(raw).key == entry["key"]

    def test_load_archetype_names_what_exists_when_asked_for_what_does_not(self) -> None:
        with pytest.raises(KeyError, match="opportunistic"):
            load_archetype("no-such-archetype")


class TestTheEnvelopesThemselves:
    @pytest.mark.parametrize("archetype", ARCHETYPES, ids=lambda a: a.key)
    def test_every_numeric_constraint_has_a_range(self, archetype: Archetype) -> None:
        """An unranged constraint is a dimension the model may set freely.

        Enforced at load time by the model, so this test is really asserting that
        the enforcement is derived from `MandateConstraints` rather than from a
        list that could be updated separately.
        """
        assert set(archetype.constraint_ranges) == set(numeric_constraint_names())

    @pytest.mark.parametrize("archetype", ARCHETYPES, ids=lambda a: a.key)
    @pytest.mark.parametrize("corner", ["min", "max"])
    def test_both_corners_are_valid_mandates_that_pass_their_own_envelope(
        self, archetype: Archetype, corner: str
    ) -> None:
        """The extremes have to be reachable.

        An envelope whose corners produce an invalid mandate is a trap laid for
        whoever generates inside it: the model would be regenerated forever
        against bounds that cannot all be satisfied at once, and the failure
        would look like a bad model rather than a bad envelope.
        """
        mandate = _mandate_at(archetype, corner)
        assert check_envelope(mandate, archetype) == []

    @pytest.mark.parametrize("archetype", ARCHETYPES, ids=lambda a: a.key)
    def test_the_base_asset_can_always_be_held(self, archetype: Archetype) -> None:
        assert archetype.base_asset in archetype.allowed_assets.must_include

    @pytest.mark.parametrize("archetype", ARCHETYPES, ids=lambda a: a.key)
    def test_the_emphases_are_distinct_and_plural(self, archetype: Archetype) -> None:
        """Two clicks producing the same vault is the failure this is judged on,
        and temperature alone will collide."""
        assert len(archetype.emphases) >= 3
        assert len({e.strip().lower() for e in archetype.emphases}) == len(archetype.emphases)

    @pytest.mark.parametrize("archetype", ARCHETYPES, ids=lambda a: a.key)
    def test_a_card_that_only_has_upsides_is_not_shippable(self, archetype: Archetype) -> None:
        """`tradeoff` is required by the schema; this asserts it was actually
        written rather than filled with the headline again."""
        assert archetype.tradeoff.strip() != archetype.headline.strip()

    @pytest.mark.parametrize("archetype", ARCHETYPES, ids=lambda a: a.key)
    def test_an_archetype_spanning_conservative_and_aggressive_promises_nothing(
        self, archetype: Archetype
    ) -> None:
        postures = set(archetype.risk_postures)
        assert not {"conservative", "aggressive"} <= postures, (
            f"'{archetype.key}' admits both extremes, so its card describes no posture at all"
        )


class TestTheGate:
    """One escape per bound kind, and the violation has to be actionable.

    Each starts from a mandate that passes and breaks exactly one thing, so a
    failure here names the check that stopped working.
    """

    @pytest.fixture
    def archetype(self) -> Archetype:
        return load_archetype("balanced-growth")

    @pytest.fixture
    def good(self, archetype: Archetype) -> Mandate:
        return _mandate_at(archetype, "min")

    def test_the_baseline_passes(self, good: Mandate, archetype: Archetype) -> None:
        assert check_envelope(good, archetype) == []

    def test_an_asset_outside_subset_of_is_caught(
        self, good: Mandate, archetype: Archetype
    ) -> None:
        escaped = good.model_copy(
            update={
                "constraints": good.constraints.model_copy(
                    update={"allowed_assets": [*good.constraints.allowed_assets, "AERO"]}
                )
            }
        )
        violations = check_envelope(escaped, archetype)
        # Two, and correctly so: balanced-growth caps the list at two entries, so
        # a third asset breaches subset_of AND max_count. Asserting exactly one
        # here would be asserting that the gate under-reports.
        assert {v.field for v in violations} == {"constraints.allowed_assets"}
        assert any("AERO" in v.message for v in violations)
        assert any("more than the maximum" in v.message for v in violations)

    def test_a_venue_outside_subset_of_is_caught(
        self, good: Mandate, archetype: Archetype
    ) -> None:
        escaped = good.model_copy(update={"permitted_venues": ["uniswap", "aqua"]})
        (violation,) = check_envelope(escaped, archetype)
        assert violation.field == "permitted_venues"
        assert "aqua" in violation.message

    def test_dropping_a_required_venue_is_caught(
        self, good: Mandate, archetype: Archetype
    ) -> None:
        escaped = good.model_copy(update={"permitted_venues": ["aave", "morpho"]})
        (violation,) = check_envelope(escaped, archetype)
        assert violation.field == "permitted_venues"
        assert "uniswap" in violation.message

    def test_a_numeric_constraint_below_its_range_is_caught(
        self, good: Mandate, archetype: Archetype
    ) -> None:
        floor = archetype.constraint_ranges["min_cash_pct"].min
        escaped = good.model_copy(
            update={"constraints": good.constraints.model_copy(update={"min_cash_pct": floor / 2})}
        )
        (violation,) = check_envelope(escaped, archetype)
        assert violation.field == "constraints.min_cash_pct"
        assert str(floor) in violation.message, "the message must name the bound, not just the value"

    def test_a_numeric_constraint_above_its_range_is_caught(
        self, good: Mandate, archetype: Archetype
    ) -> None:
        ceiling = archetype.constraint_ranges["max_slippage_bps"].max
        escaped = good.model_copy(
            update={
                "constraints": good.constraints.model_copy(
                    update={"max_slippage_bps": ceiling + 1}
                )
            }
        )
        (violation,) = check_envelope(escaped, archetype)
        assert violation.field == "constraints.max_slippage_bps"

    def test_a_range_is_inclusive_at_both_ends(self, good: Mandate, archetype: Archetype) -> None:
        """`min == max` is how an envelope pins a value, so an exclusive bound
        would make a pinned dimension unsatisfiable."""
        band = archetype.constraint_ranges["tolerance_band_pct"]
        for edge in (band.min, band.max):
            pinned = good.model_copy(
                update={
                    "constraints": good.constraints.model_copy(
                        update={"tolerance_band_pct": edge}
                    )
                }
            )
            assert check_envelope(pinned, archetype) == []

    def test_a_posture_the_archetype_does_not_admit_is_caught(
        self, good: Mandate, archetype: Archetype
    ) -> None:
        escaped = good.model_copy(update={"risk_posture": "aggressive"})
        (violation,) = check_envelope(escaped, archetype)
        assert violation.field == "risk_posture"

    def test_the_wrong_base_asset_is_caught(self, good: Mandate, archetype: Archetype) -> None:
        escaped = good.model_copy(update={"base_asset": "WETH"})
        violations = check_envelope(escaped, archetype)
        assert any(v.field == "base_asset" for v in violations)

    def test_a_missing_required_persona_is_caught(
        self, good: Mandate, archetype: Archetype
    ) -> None:
        escaped = good.model_copy(update={"persona": None})
        (violation,) = check_envelope(escaped, archetype)
        assert violation.field == "persona"

    def test_every_violation_is_reported_not_just_the_first(
        self, good: Mandate, archetype: Archetype
    ) -> None:
        """A regeneration that fixes one fault and trips the next costs a round
        trip per fault — the same lesson the schema error reporting already paid
        for."""
        escaped = good.model_copy(
            update={
                "base_asset": "WETH",
                "risk_posture": "aggressive",
                "permitted_venues": ["aqua"],
            }
        )
        fields = {v.field for v in check_envelope(escaped, archetype)}
        assert {"base_asset", "risk_posture", "permitted_venues"} <= fields


class TestTheEnvelopeRefusesToLoadWhenItAdmitsNothing:
    """Load-time guards, each pinned to a mistake that is easy to make by hand."""

    def _base(self) -> dict:
        raw = json.loads(
            (ARCHETYPE_DIR / "balanced-growth.json").read_text(encoding="utf-8")
        )
        return raw

    def test_must_include_outside_subset_of_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="admits nothing"):
            SetBound.model_validate({"subset_of": ["USDC"], "must_include": ["WETH"]})

    def test_min_count_above_max_count_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exceeds max_count"):
            SetBound.model_validate({"subset_of": ["A", "B", "C"], "min_count": 3, "max_count": 2})

    def test_an_inverted_range_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="range is empty"):
            NumericRange.model_validate({"min": 0.5, "max": 0.2})

    def test_a_missing_range_is_rejected_at_load(self) -> None:
        raw = self._base()
        del raw["constraint_ranges"]["min_cash_pct"]
        with pytest.raises(ValidationError, match="min_cash_pct"):
            Archetype.model_validate(raw)

    def test_a_range_for_something_that_is_not_a_constraint_is_rejected(self) -> None:
        raw = self._base()
        raw["constraint_ranges"]["max_drawdown_pct"] = {"min": 0, "max": 1}
        with pytest.raises(ValidationError, match="max_drawdown_pct"):
            Archetype.model_validate(raw)

    def test_a_cash_floor_that_crowds_out_every_position_is_rejected(self) -> None:
        """The generalisation of a real Wave 2 preset bug."""
        raw = self._base()
        raw["constraint_ranges"]["min_cash_pct"]["max"] = 0.9
        raw["constraint_ranges"]["max_position_pct"]["min"] = 0.3
        with pytest.raises(ValidationError, match="can never use it"):
            Archetype.model_validate(raw)

    def test_that_same_check_does_not_fire_on_a_base_asset_only_envelope(self) -> None:
        """`conservative-income` permits only USDC, so `max_position_pct` binds
        on nothing and a 0.4 cash floor beside a 1.0 cap is correct, not a
        contradiction. Rejecting it is the mistake that was made once already on
        the equivalent preset — fixed there in the test, and this pins it."""
        assert load_archetype("conservative-income").constraint_ranges["min_cash_pct"].max == 0.4

    def test_repeating_an_emphasis_is_rejected(self) -> None:
        raw = self._base()
        raw["emphases"][1] = raw["emphases"][0]
        with pytest.raises(ValidationError, match="repeats an emphasis"):
            Archetype.model_validate(raw)

    def test_a_base_asset_the_mandate_could_omit_is_rejected(self) -> None:
        raw = self._base()
        raw["allowed_assets"]["must_include"] = []
        with pytest.raises(ValidationError, match="cannot honour a redemption"):
            Archetype.model_validate(raw)
