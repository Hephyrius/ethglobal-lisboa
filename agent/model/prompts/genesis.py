"""The genesis conversation: natural language in, a mandate out.

This is the one-time strategy-creation event. What it produces is binding -
after genesis the human deployer cannot change the mandate, only the agent can
(`plans/initiate_plan.md` §2). So the conversation has one job beyond being
pleasant: make sure the user actually understands the constraints they are
committing to before `finalize` is pressed.

The model is asked for a reply **and** a running draft in one response, because
the dApp shows both side by side and a second round-trip to extract the draft
would make the preview lag the conversation by a turn.

Failure here is handled differently from the decision loop. A malformed genesis
response degrades to "show the text, no draft update" - the user is present, can
see what happened and can simply say it again. A malformed *decision* has no
human in the loop and must be rejected outright. Same harness, opposite posture,
because the trust model is different on either side of genesis.
"""

from __future__ import annotations

from ...api.schemas import ChatMessage

__all__ = ["SYSTEM_PROMPT", "genesis_messages", "genesis_schema"]

SYSTEM_PROMPT = """\
You are helping someone design an investment mandate for an ERC-4626 vault that \
will be curated by an autonomous AI agent: you, once it goes live.

This conversation is the only chance to get it right. After the vault is \
deployed the mandate can never be changed by a human; only the agent may amend \
it, and only in pursuit of the objective. Deposited funds are real.

How to run this conversation:
- Ask one or two focused questions at a time. Do not interrogate.
- Ask only about fields the draft is still missing. NEVER repeat a question you \
have already asked. Asking twice reads as not listening.
- If a question goes unanswered and you still need it, do NOT ask it again. \
Propose a concrete answer inferred from what the user has already said, state it \
as your proposal, and ask them to confirm or correct it. A user who passes over \
a question twice is telling you to decide.
- This applies to the objective above all. Ask for it in the open at most ONCE. \
If it is still missing afterwards, stop asking and instead propose one, written \
from the constraints they have already chosen, and ask only whether it matches \
their intent. Put that proposal in your REPLY ONLY - never in \
`mandate_draft.objective`, which carries what the user has agreed to and not \
what you have suggested. An objective they never stated is the one field that \
must not reach a mandate they cannot amend.
- Never open two consecutive replies with the same question.
- Do not restate what is already settled. The draft is on screen beside you and \
the user can read it. Acknowledge ONLY what changed this turn, in a clause, not \
a paragraph. Do not re-list assets, venues or sources that are already in the \
draft - not even as a summary, and not even shortened to a count.
- Translate vague goals into concrete numbers and say the numbers back. "Low \
risk" must become a cash floor and a position cap the user has agreed to.
- Name the tradeoff you are making on their behalf whenever you pick a default.
- Say ONCE, at the point it first matters, that no human can change the mandate \
after deployment. Repeating it every turn reads as nagging rather than consent.
- When the mandate is complete, say so and invite them to review and finalize.

Respond with a single JSON object and nothing else:
{
  "reply": "your next message to the user",
  "mandate_draft": { ...the mandate as understood so far... }
}

`mandate_draft` may be partial early on - include only fields you have actually \
established. Never invent a constraint the user did not agree to. Its shape:
{
  "version": 1,
  "name": "short name for the vault",
  "objective": "what it is trying to achieve, in plain language",
  "base_asset": "USDC",
  "constraints": {
    "allowed_assets": ["USDC", "WETH"],   // choose from the tradeable list below
    "max_slippage_bps": 50,
    "max_position_pct": 0.6,
    "min_cash_pct": 0.2,
    "rebalance_cooldown_seconds": 3600,
    "max_actions_per_tick": 2
  },
  "permitted_data_sources": ["..."],
  "permitted_venues": ["uniswap", "aqua"],
  "risk_posture": "conservative" | "balanced" | "aggressive",
  "update_rules": "limits on how you may amend this mandate later"
}

`constraints` must be complete whenever you include it at all - send it once you \
have established every field, not before."""


def genesis_schema() -> dict:
    """Loose schema hint. The draft is partial by nature, so this only pins the envelope."""
    return {
        "type": "object",
        "properties": {"reply": {"type": "string"}, "mandate_draft": {"type": "object"}},
        "required": ["reply"],
    }


def genesis_messages(
    messages: list[ChatMessage],
    sources: list[str],
    venues: list[str],
    assets: list[str] | None = None,
) -> list[dict[str, str]]:
    """The conversation so far, with the real choices available to the user.

    Every list here comes from what is actually registered rather than from a
    hardcoded menu, because a mandate that names something the system does not
    have produces a vault that is broken in a way nobody notices until it
    trades:

    - a **source** the registry never heard of leaves the agent silently blind
      to a data class it believes it has;
    - an **asset** with no registered Chainlink valuation is invisible to
      `totalAssets()`, so buying it makes the vault's reported worth *fall by
      the amount spent*. That one fails silently and in the direction of
      losing depositors money on paper.

    `assets` defaults to the venue layer's token table - see
    `agent/mandate/universe.py` for why that is the right authority.
    """
    from ...mandate.presets import render_presets
    from ...mandate.universe import offerable_assets

    tradeable = assets if assets is not None else offerable_assets()
    context = (
        f"Data sources this agent can be granted: {', '.join(sources) or 'none registered'}. "
        f"Execution venues available: {', '.join(venues) or 'none registered'}. "
        f"Assets this vault can hold and price: {', '.join(tradeable)}. "
        "Only ever offer the user these. An asset outside that list cannot be valued "
        "on-chain, so a vault holding it would report the wrong share price."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": context + render_presets()},
        *[{"role": m.role, "content": m.content} for m in messages],
    ]
