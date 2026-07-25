"""Asking the model to invent a strategy inside a fixed set of bounds.

This prompt is different from every other one in this lane in a way that decides
how it is written: **nobody reads the answer.** Genesis has a human in the loop
who can restate themselves; the decision loop has six validation layers and a
mandate that was agreed in advance. Here one click produces a mandate and that
mandate is deployed on-chain unread, so `check_envelope()` is the entire review
process and this prompt's job is to make passing it likely rather than lucky.

Three consequences.

**The envelope is restated as numbers, not adjectives.** Same reason the decision
prompt restates the mandate that way: the rejection message the model will get
back names a field and a range, so the instruction has to be in the same terms
or a retry reads as a contradiction.

**The emphasis is what makes two clicks differ, and it is chosen by the caller.**
Temperature alone collides — that is the observation `Archetype.emphases`
exists for. Each emphasis is a materially different *angle on the same bounds*,
so the mandate that comes back differs in structure and in prose rather than in
wording alone.

**The model writes the parts a human would have written.** `name`, `objective`
and `update_rules` are prose a depositor reads; the numbers are the part that
must sit inside the envelope. Asking for both in one call is what makes this a
generated strategy rather than a randomised template.
"""

from __future__ import annotations

from collections.abc import Sequence

from curator_schema import Archetype, Mandate

__all__ = ["ARCHETYPE_SYSTEM_PROMPT", "archetype_messages", "archetype_schema"]

ARCHETYPE_SYSTEM_PROMPT = """\
You design mandates for autonomous ERC-4626 vaults. A mandate is the complete, \
permanent instruction set an AI curator will follow with real depositor money, \
and it is the only thing standing between that curator and a bad trade.

You are given an ARCHETYPE: a set of bounds. Your job is to invent one specific \
strategy that lives inside those bounds and to write it down as a mandate.

What matters:
- Every number you choose must be inside the stated range. A mandate outside \
its bounds is discarded and you are asked again, so there is nothing to gain \
by reaching.
- Choose deliberately within each range and say why in `objective`. The ranges \
are wide because different strategies want different points in them, not \
because the midpoint is correct.
- `name` is what a depositor sees. Make it specific to the strategy you chose - \
"Deep Liquidity USDC Income" says something, "Conservative Vault" does not.
- `objective` is read by the curator on every single tick and is the main thing \
steering it. Write an instruction, not a description: say what to prefer, what \
to avoid, and what would make you wrong.
- `update_rules` says when the curator may amend this mandate. Be specific about \
conditions; the curator can rewrite its own constraints and this sentence is \
most of what governs that.

Respond with a single JSON object and nothing else. No prose, no code fences."""


def archetype_schema(archetype: Archetype | None = None) -> dict:
    """JSON Schema for a `Mandate`, narrowed to one archetype's bounds.

    **This is what makes a generation land first try rather than after three
    corrections**, and finding out why is the most useful thing this module
    learned. Given the plain `Mandate` schema, the model returned six of seven
    constraints correctly and `tolerance_band_pct: 0.5` — every time, ignoring
    the retry that told it the permitted range was 0 to 0.03.

    It was not ignoring the correction. `Mandate` allows `tolerance_band_pct` up
    to 0.5, so the JSON Schema handed to the backend for constrained decoding
    said `maximum: 0.5` while the prose said 0.03. **The prompt and the schema
    disagreed, and the model believed the schema** — which is the right instinct
    on its part, and a bug on ours.

    So the envelope is pushed down into the schema itself: numeric ranges become
    `minimum`/`maximum`, and the set-valued fields become enums. A backend with
    constrained decoding then *cannot* emit an out-of-range number, and one
    without it at least reads bounds that agree with the instruction.

    `check_envelope()` still runs and is still the authority. This narrows what
    the model is likely to produce; it does not decide what may deploy.
    """
    schema = Mandate.model_json_schema()
    if archetype is None:
        return schema

    constraints = _constraints_schema(schema)
    if constraints is not None:
        for name, allowed in archetype.constraint_ranges.items():
            if (field := constraints.get(name)) is not None:
                # Intersected, not replaced: the mandate's own bound is a real
                # limit and an archetype must never be able to widen one.
                field["minimum"] = max(allowed.min, field.get("minimum", allowed.min))
                field["maximum"] = min(allowed.max, field.get("maximum", allowed.max))
                # `min_cash_pct` defaults to 0.0 and this envelope's floor is
                # 0.2, so the unclamped schema advertises a default its own
                # bounds forbid. Left alone that is a legal-looking value the
                # model can copy straight into a rejection.
                if (fallback := field.get("default")) is not None:
                    field["default"] = min(max(fallback, field["minimum"]), field["maximum"])
        _enum_items(constraints.get("allowed_assets"), archetype.allowed_assets.subset_of)

    top = schema.get("properties", {})
    _enum_items(top.get("permitted_venues"), archetype.permitted_venues.subset_of)
    _enum_items(
        top.get("permitted_data_sources"), archetype.permitted_data_sources.subset_of
    )
    if (posture := top.get("risk_posture")) is not None:
        posture.pop("allOf", None)
        posture.pop("$ref", None)
        posture["enum"] = list(archetype.risk_postures)
    return schema


def _constraints_schema(schema: dict) -> dict | None:
    """`MandateConstraints.properties`, wherever pydantic put it.

    Looked up rather than assumed: pydantic inlines a nested model or hoists it
    into `$defs` depending on how often it is referenced, and a hardcoded path
    would silently stop narrowing anything the day that changed — leaving the
    schema and the prompt disagreeing again, with no error to notice.
    """
    for definition in schema.get("$defs", {}).values():
        if "min_cash_pct" in definition.get("properties", {}):
            return definition["properties"]
    inline = schema.get("properties", {}).get("constraints", {}).get("properties")
    return inline if inline and "min_cash_pct" in inline else None


def _enum_items(field: dict | None, allowed: list[str]) -> None:
    """Constrain an array field's members to `allowed`, in place."""
    if field is None:
        return
    items = field.get("items")
    if isinstance(items, dict):
        items.pop("$ref", None)
        items.pop("allOf", None)
        items["enum"] = list(allowed)
    else:
        field["items"] = {"type": "string", "enum": list(allowed)}


def _range_lines(archetype: Archetype) -> list[str]:
    """One line per numeric constraint, in the mandate's own field names.

    Named identically to `MandateConstraints` on purpose: the model is filling in
    a JSON object with those keys, and a prompt that calls `min_cash_pct` "the
    cash floor" makes it guess at the mapping.
    """
    lines = []
    for name, allowed in archetype.constraint_ranges.items():
        if allowed.min == allowed.max:
            lines.append(f"- {name}: exactly {allowed.min:g}. Not a choice.")
        else:
            lines.append(f"- {name}: any value from {allowed.min:g} to {allowed.max:g}")
    return lines


def _set_line(label: str, bound) -> str:
    ceiling = bound.max_count if bound.max_count is not None else len(bound.subset_of)
    parts = [f"- {label}: choose {bound.min_count}"]
    parts.append(f"to {ceiling}" if ceiling != bound.min_count else "")
    parts.append(f"from {', '.join(bound.subset_of)}.")
    if bound.must_include:
        parts.append(f"Must include {', '.join(bound.must_include)}.")
    return " ".join(p for p in parts if p)


def archetype_messages(
    archetype: Archetype,
    emphasis: str,
    *,
    nonce: str,
    context: str = "",
    avoid: Sequence[str] = (),
) -> list[dict[str, str]]:
    """The conversation that asks for one generated mandate.

    `emphasis` is one of the archetype's own rotating angles and is the
    structural half of *two clicks, two different vaults* — it is passed in
    rather than picked here so that the caller, which knows how many vaults this
    archetype already has, controls the rotation.

    `nonce` and `context` are the other half: a value that differs per call, and
    a snapshot of what the market looked like when the button was pressed. Both
    are stated as things to design *around*, not as data to cite — this mandate
    will outlive the snapshot by weeks, so a strategy that hardcodes today's rate
    is a worse strategy, not a more informed one.

    `avoid` names strategies this archetype has already produced. Only used on a
    regeneration, and phrased as *what to differ from* rather than *what is
    forbidden*, because the second invites the model to invert a constraint.
    """
    limits = [
        f"Base asset: {archetype.base_asset}. Fixed - the vault accounts in it "
        "and it cannot be changed after deployment.",
        _set_line("constraints.allowed_assets", archetype.allowed_assets),
        _set_line("permitted_venues", archetype.permitted_venues),
        _set_line("permitted_data_sources", archetype.permitted_data_sources),
        f"- risk_posture: one of {', '.join(archetype.risk_postures)}",
        *_range_lines(archetype),
    ]
    if archetype.persona is not None and archetype.persona.required:
        convictions = archetype.persona.conviction or ["low", "medium", "high"]
        limits.append(
            f"- persona: required. `conviction` must be one of {', '.join(convictions)}. "
            "Give it a name and a voice that match the strategy you chose."
        )

    body = "\n".join(limits)
    lines = [
        f"ARCHETYPE: {archetype.name}",
        f"What it is for: {archetype.headline}",
        f"What it gives up: {archetype.tradeoff}",
        "",
        "BOUNDS. Every one of these is checked, and a mandate outside them is "
        "discarded unread:",
        body,
        "",
        f"YOUR ANGLE THIS TIME: {emphasis}",
        "",
        f"Design token (make this strategy distinct; do not mention it): {nonce}",
    ]
    if context:
        lines += [
            "",
            "What the market looks like right now. Design around it, do not "
            "hardcode it - this mandate will outlive these numbers:",
            context,
        ]
    if avoid:
        lines += [
            "",
            "This archetype has already produced the strategies below. Yours must "
            "be materially different - a different point in the ranges, a "
            "different emphasis, a different name:",
            *[f"- {name}" for name in avoid],
        ]
    lines += [
        "",
        "Set `version` to 1. Write the mandate now, as a single JSON object.",
    ]

    return [
        {"role": "system", "content": ARCHETYPE_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]
