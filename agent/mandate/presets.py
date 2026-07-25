"""Reading Lane F's mandate presets, for the genesis conversation.

Wave 2 §3.3 ships `packages/schema/presets/` as a frozen fixture set, and §B5
asks this lane to *"read F's presets and offer them in the genesis conversation
as named starting points with their tradeoffs, then let the user amend."*

Two properties matter more than the loading:

**Both halves of every preset get offered.** `index.json` carries a `headline`
and a `tradeoff` per preset, and the tradeoff is the half that a user actually
needs — "lend USDC only" sounds strictly safe until you read that it gives up
every source of return except lending. A genesis flow that lists benefits and
omits costs is a sales page, and this one produces a mandate that cannot be
changed by a human afterwards.

**Preset prose is coerced to ASCII.** These strings are written in another
lane's file and flow straight into a prompt. One smart quote or em dash makes
the whole prompt non-ASCII, which Lane C established mangles on a Windows
console — and `agent/tests/test_prompt_rendering.py` asserts the decision prompt
is clean, so an unguarded genesis prompt would be the one hole left.

A missing or malformed index degrades to an empty list. Genesis without presets
is the pre-Wave-2 conversation, which worked; genesis that raises on a missing
fixture file is a broken product.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import cache

from ..config import REPO_ROOT

__all__ = ["Preset", "load_presets", "render_presets"]

log = logging.getLogger(__name__)

PRESETS_DIR = REPO_ROOT / "packages" / "schema" / "presets"

#: Written by another lane, rendered into a prompt. See the module docstring.
_ASCII = {
    "—": " - ",
    "–": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    " ": " ",
}


def _asciify(text: str) -> str:
    for bad, good in _ASCII.items():
        text = text.replace(bad, good)
    return text.encode("ascii", "ignore").decode("ascii")


@dataclass(frozen=True)
class Preset:
    """One named starting point, with the cost of choosing it."""

    key: str
    headline: str
    tradeoff: str
    persona: str | None = None


@cache
def load_presets() -> tuple[Preset, ...]:
    """Every preset Lane F publishes, or an empty tuple.

    Cached: the files are frozen fixtures and genesis reads them on every turn.
    """
    index = PRESETS_DIR / "index.json"
    if not index.is_file():
        log.info("no preset index at %s; genesis will not offer starting points", index)
        return ()

    try:
        entries = json.loads(index.read_text(encoding="utf-8")).get("presets") or []
    except (ValueError, OSError) as exc:
        log.warning("could not read the preset index (%s); offering none", exc)
        return ()

    presets: list[Preset] = []
    for entry in entries:
        key = entry.get("key")
        headline = entry.get("headline")
        tradeoff = entry.get("tradeoff")
        if not (key and headline and tradeoff):
            # A preset without its tradeoff is worse than no preset: it would be
            # offered as an unqualified good.
            log.warning("skipping preset %r: missing headline or tradeoff", key)
            continue
        presets.append(
            Preset(
                key=str(key),
                headline=_asciify(str(headline)),
                tradeoff=_asciify(str(tradeoff)),
                persona=_asciify(str(entry["persona"])) if entry.get("persona") else None,
            )
        )
    return tuple(presets)


def render_presets() -> str:
    """The genesis prompt block, or "" when there are none to offer."""
    presets = load_presets()
    if not presets:
        return ""

    lines = [
        "",
        "STARTING POINTS you may offer. Each is a complete mandate the user can "
        "take and then amend by talking to you. Always give the tradeoff in the "
        "same breath as the headline - a user cannot consent to a cost you did "
        "not mention, and after genesis they cannot change any of it.",
        "",
    ]
    for preset in presets:
        lines.append(f"- {preset.key}: {preset.headline}")
        lines.append(f"  Tradeoff: {preset.tradeoff}")
        if preset.persona:
            lines.append(f"  Curated as: {preset.persona}")
    lines.append("")
    lines.append(
        "Offer these by name when the user is unsure where to begin. Do not "
        "invent a fourth, and do not present one as the safe or obvious choice: "
        "which tradeoff is acceptable is the user's judgement, not yours."
    )
    return "\n".join(lines)
