"""Archetypes — the constraint envelopes a generated mandate must sit inside.

## What this is for

An archetype is **bounds**, not a template. One click on a card asks the model
for a fresh mandate; this module answers the only question that keeps that safe:
*does what it wrote sit inside what the card promised?*

Nobody reads a generated mandate before it goes on-chain. There is no genesis
conversation, no preview, no user input beyond the archetype key. So
`check_envelope()` is the whole review process, and a violation means
**regenerate — never deploy.**

## Why the field names are the mandate's field names

`Archetype.constraint_ranges` is keyed by the exact field names of
`MandateConstraints`, so the check is a loop over keys rather than a
hand-written mapping. Two things follow, and both are the point:

- A constraint added to `MandateConstraints` with no range declared here is
  caught at **load** time by `_ranges_cover_every_numeric_constraint`, not
  discovered later as a dimension the model was silently free to choose.
- There is no second list of field names to fall out of step with the first.

## One gate, two readers

The gate is Python and only Python. Lane B calls `check_envelope()`; nothing in
TypeScript decides whether a mandate may deploy, so there is no second
implementation to disagree with this one. The zod mirror gives Lane E the type
and a describer that generates card copy *mechanically from the same JSON*, so a
card cannot promise a bound the envelope does not hold.

## Distinct from `presets/`

Presets are fixed mandates that seed the curator conversation, and a human reads
one before it deploys. They are unchanged and unrelated. An archetype shares no
file, no directory and no schema with them.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .models import Frozen, Mandate, MandateConstraints

__all__ = [
    "ARCHETYPE_DIR",
    "Archetype",
    "ArchetypePersona",
    "EnvelopeViolation",
    "NumericRange",
    "SetBound",
    "check_envelope",
    "load_archetype",
    "load_archetypes",
    "numeric_constraint_names",
]


def _archetype_dir() -> Path:
    """`packages/schema/archetypes/`, wherever this module was installed from.

    Prefers a copy packaged into the wheel (`_data/archetypes`) and falls back to
    the repository layout, which is how every lane actually runs. Checked in that
    order so an installed copy is never shadowed by a checkout that happens to be
    on the path.
    """
    packaged = Path(__file__).resolve().parent / "_data" / "archetypes"
    if packaged.is_dir():
        return packaged
    # curator_schema/ -> python/ -> packages/schema/
    return Path(__file__).resolve().parents[2] / "archetypes"


ARCHETYPE_DIR = _archetype_dir()


def numeric_constraint_names() -> tuple[str, ...]:
    """Every numeric field of `MandateConstraints`, read off the model itself.

    Derived rather than listed so that adding a constraint to the mandate makes
    every archetype fail to load until it declares a range for it. A hardcoded
    tuple here would instead let the new dimension default to unbounded, which
    is the one failure mode an envelope exists to prevent.
    """
    return tuple(
        name
        for name, field in MandateConstraints.model_fields.items()
        if field.annotation in (int, float)
    )


class NumericRange(Frozen):
    """A closed interval, inclusive at both ends. `min == max` pins the value."""

    min: float
    max: float

    @model_validator(mode="after")
    def _ordered(self) -> NumericRange:
        if self.min > self.max:
            raise ValueError(f"range is empty: min {self.min} > max {self.max}")
        return self

    def contains(self, value: float) -> bool:
        return self.min <= value <= self.max


class SetBound(Frozen):
    """Bounds on one of the mandate's list-valued fields.

    `subset_of` is the ceiling and `must_include` the floor. The ceiling is the
    field that makes "the model invents a strategy and it deploys unread" safe
    enough to ship — everything else here is about coherence.
    """

    subset_of: list[str] = Field(min_length=1)
    must_include: list[str] = Field(default_factory=list)
    min_count: int = Field(default=1, ge=1)
    #: None means `len(subset_of)`.
    max_count: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _admits_something(self) -> SetBound:
        if stray := sorted(set(self.must_include) - set(self.subset_of)):
            raise ValueError(
                f"must_include names {stray}, which subset_of does not permit — "
                "this envelope admits nothing"
            )
        ceiling = self.max_count if self.max_count is not None else len(self.subset_of)
        if self.min_count > ceiling:
            raise ValueError(f"min_count {self.min_count} exceeds max_count {ceiling}")
        if ceiling > len(self.subset_of):
            raise ValueError(
                f"max_count {ceiling} exceeds the {len(self.subset_of)} entries in subset_of"
            )
        if len(self.must_include) > ceiling:
            raise ValueError(
                f"must_include has {len(self.must_include)} entries but max_count is {ceiling}"
            )
        return self


class ArchetypePersona(Frozen):
    """Whether the generated mandate carries a persona, and which convictions.

    Conviction steers sizing *within* `max_position_pct` and widens nothing, so
    this bound is about the card and the vault agreeing on character — not about
    safety. It is listed anyway because an "Opportunistic" vault that argues in a
    timid voice misrepresents what the depositor chose.
    """

    required: bool
    conviction: list[Literal["low", "medium", "high"]] | None = None


class Archetype(Frozen):
    version: int = Field(ge=1)
    key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,40}$")
    name: str = Field(min_length=1, max_length=80)
    headline: str = Field(min_length=1, max_length=120)
    tradeoff: str = Field(min_length=1, max_length=240)
    #: Fixed, not ranged: share pricing depends on it and it is bound into the
    #: vault at deployment, so it is not a dimension a generation may vary.
    base_asset: str
    allowed_assets: SetBound
    permitted_venues: SetBound
    permitted_data_sources: SetBound
    risk_postures: list[Literal["conservative", "balanced", "aggressive"]] = Field(min_length=1)
    constraint_ranges: dict[str, NumericRange]
    #: Materially different angles, one per click. Uniqueness has to be
    #: structural — temperature alone collides, and two clicks producing the same
    #: vault is the failure this feature is judged on.
    emphases: list[str] = Field(min_length=3)
    persona: ArchetypePersona | None = None

    @model_validator(mode="after")
    def _ranges_cover_every_numeric_constraint(self) -> Archetype:
        expected = set(numeric_constraint_names())
        declared = set(self.constraint_ranges)
        if missing := sorted(expected - declared):
            raise ValueError(
                f"archetype '{self.key}' declares no range for {missing} — "
                "an unranged constraint is a dimension the model may set freely, "
                "which is the opposite of an envelope"
            )
        if unknown := sorted(declared - expected):
            raise ValueError(
                f"archetype '{self.key}' ranges {unknown}, which is not a numeric "
                f"constraint on MandateConstraints; known: {sorted(expected)}"
            )
        return self

    @model_validator(mode="after")
    def _base_asset_is_always_holdable(self) -> Archetype:
        if self.base_asset not in self.allowed_assets.must_include:
            raise ValueError(
                f"base_asset '{self.base_asset}' is not in allowed_assets.must_include — "
                "a mandate may omit it, and a vault that cannot hold its own accounting "
                "asset cannot honour a redemption"
            )
        return self

    @model_validator(mode="after")
    def _a_non_base_position_can_actually_be_taken(self) -> Archetype:
        """If non-base assets are permitted, the cash floor must leave room for one.

        The generalisation of a real Wave 2 preset bug. When the envelope permits
        only the base asset the position cap binds on nothing and this is
        inapplicable — checking it unconditionally would reject a correct
        conservative envelope, which is exactly the mistake made once already.
        """
        if len(self.allowed_assets.subset_of) <= 1:
            return self
        floor = self.constraint_ranges["min_cash_pct"].max
        cap = self.constraint_ranges["max_position_pct"].min
        if floor + cap > 1:
            raise ValueError(
                f"archetype '{self.key}' permits non-base assets, but a mandate at "
                f"min_cash_pct {floor} with max_position_pct {cap} cannot hold a full "
                "position — the envelope would generate vaults that can never use it"
            )
        return self

    @model_validator(mode="after")
    def _emphases_are_distinct(self) -> Archetype:
        seen = [e.strip().lower() for e in self.emphases]
        if len(set(seen)) != len(seen):
            raise ValueError(
                f"archetype '{self.key}' repeats an emphasis — the rotation is the "
                "structural half of 'two clicks, two different vaults'"
            )
        return self


class EnvelopeViolation(Frozen):
    """One way a generated mandate escaped its envelope.

    `field` is the mandate's own dotted path, so a regeneration prompt can name
    the field the model got wrong rather than restating the whole envelope.
    """

    field: str
    message: str


@lru_cache(maxsize=1)
def load_archetypes() -> tuple[Archetype, ...]:
    """Every archetype, in the index's order.

    Reads `archetypes/index.json` rather than globbing the directory: the index
    is what the dApp offers, and a file present but unlisted must not silently
    become deployable. The conformance test asserts the two agree.
    """
    index_path = ARCHETYPE_DIR / "index.json"
    entries = json.loads(index_path.read_text(encoding="utf-8"))["archetypes"]
    loaded: list[Archetype] = []
    for entry in entries:
        path = ARCHETYPE_DIR.parent / entry["file"]
        archetype = Archetype.model_validate_json(path.read_text(encoding="utf-8"))
        if archetype.key != entry["key"]:
            raise ValueError(
                f"{entry['file']} declares key '{archetype.key}' but the index lists "
                f"'{entry['key']}' — the URL and the envelope would disagree"
            )
        loaded.append(archetype)
    return tuple(loaded)


def load_archetype(key: str) -> Archetype:
    """One archetype by key. Raises `KeyError` naming what is available."""
    for archetype in load_archetypes():
        if archetype.key == key:
            return archetype
    available = ", ".join(a.key for a in load_archetypes())
    raise KeyError(f"no archetype '{key}'; available: {available}")


def _check_set(
    field: str, actual: list[str], bound: SetBound
) -> list[EnvelopeViolation]:
    found: list[EnvelopeViolation] = []
    values = list(actual)
    if stray := sorted(set(values) - set(bound.subset_of)):
        found.append(
            EnvelopeViolation(
                field=field,
                message=(
                    f"names {stray}, which this archetype does not permit; "
                    f"allowed: {sorted(bound.subset_of)}"
                ),
            )
        )
    if missing := sorted(set(bound.must_include) - set(values)):
        found.append(
            EnvelopeViolation(
                field=field, message=f"omits {missing}, which this archetype requires"
            )
        )
    ceiling = bound.max_count if bound.max_count is not None else len(bound.subset_of)
    if len(values) < bound.min_count:
        found.append(
            EnvelopeViolation(
                field=field,
                message=f"has {len(values)} entries, fewer than the minimum {bound.min_count}",
            )
        )
    if len(values) > ceiling:
        found.append(
            EnvelopeViolation(
                field=field,
                message=f"has {len(values)} entries, more than the maximum {ceiling}",
            )
        )
    return found


def check_envelope(mandate: Mandate, archetype: Archetype) -> list[EnvelopeViolation]:
    """Every way this mandate escapes this envelope. Empty means it may deploy.

    Returns all violations rather than the first: a regeneration that fixes one
    field and trips the next costs a round trip per fault, and the same lesson
    was already paid for in the schema error reporting.

    This does **not** re-validate the mandate itself — that is `Mandate`'s job
    and has already happened by the time a `Mandate` exists.
    """
    found: list[EnvelopeViolation] = []

    if mandate.base_asset != archetype.base_asset:
        found.append(
            EnvelopeViolation(
                field="base_asset",
                message=(
                    f"is '{mandate.base_asset}' but this archetype accounts in "
                    f"'{archetype.base_asset}'"
                ),
            )
        )

    found += _check_set(
        "constraints.allowed_assets",
        mandate.constraints.allowed_assets,
        archetype.allowed_assets,
    )
    found += _check_set(
        "permitted_venues", list(mandate.permitted_venues), archetype.permitted_venues
    )
    found += _check_set(
        "permitted_data_sources",
        mandate.permitted_data_sources,
        archetype.permitted_data_sources,
    )

    if mandate.risk_posture not in archetype.risk_postures:
        found.append(
            EnvelopeViolation(
                field="risk_posture",
                message=(
                    f"is '{mandate.risk_posture}'; this archetype admits "
                    f"{sorted(archetype.risk_postures)}"
                ),
            )
        )

    for name, allowed in archetype.constraint_ranges.items():
        value = getattr(mandate.constraints, name)
        if not allowed.contains(value):
            found.append(
                EnvelopeViolation(
                    field=f"constraints.{name}",
                    message=f"is {value}, outside the permitted {allowed.min}–{allowed.max}",
                )
            )

    if archetype.persona is not None:
        if archetype.persona.required and mandate.persona is None:
            found.append(
                EnvelopeViolation(
                    field="persona", message="is absent, and this archetype requires one"
                )
            )
        elif (
            mandate.persona is not None
            and archetype.persona.conviction is not None
            and mandate.persona.conviction not in archetype.persona.conviction
        ):
            found.append(
                EnvelopeViolation(
                    field="persona.conviction",
                    message=(
                        f"is '{mandate.persona.conviction}'; this archetype admits "
                        f"{sorted(archetype.persona.conviction)}"
                    ),
                )
            )

    return found
