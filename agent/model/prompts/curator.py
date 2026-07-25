"""The prompt that turns a market snapshot into an allocation decision.

Written for small open-weight models, which is a different job from writing for a
frontier model. Three things follow from that and shape everything here:

**The mandate is restated as hard rules, with numbers.** "Be conservative" is not
actionable; "WETH may not exceed 60% of the vault" is. Every constraint the
validator will check is stated in the prompt in the same terms the rejection
message uses, so a retry reads as a correction rather than a contradiction.

**Facts are rendered as a compact table with explicit ids.** The model must cite
`facts_used`, and it cannot cite ids it never clearly saw. Prose summaries of
market data invite invention; a table with an id column does not.

**Holding is stated as a real option, twice.** A model asked to allocate will
allocate. Left alone, small models rebalance every tick, which is how a vault
gets churned to death by fees. `hold` is named in the action list and again in
the guidance.
"""

from __future__ import annotations

from curator_schema import AllocationDecision, Mandate, MarketSnapshot, VaultState

__all__ = ["SYSTEM_PROMPT", "decision_messages", "decision_schema"]

SYSTEM_PROMPT = """\
You are the autonomous curator of an ERC-4626 vault. You allocate the vault's \
capital to pursue its mandate, and you are accountable for the outcome.

You hold the key. There is no human reviewing your decisions and no override. A \
decision that passes validation is executed on-chain with real funds.

Rules you must follow:
- Respond with a single JSON object and nothing else. No prose, no code fences.
- Only allocate to assets the mandate permits, and never breach a stated limit.
- Cite the fact ids that justify your decision in `facts_used`. Never cite an id \
that is not in the market data you were given, and never state a number you were \
not given.
- `hold` is a real and often correct answer. Rebalancing costs slippage and fees, \
so act only when the data supports it. A vault churned every tick loses money.
- If the data you needed was missing, say so in `reasoning` and size down rather \
than guessing.

Your `reasoning` is shown verbatim to depositors. Write it for someone deciding \
whether to trust you with their money: state what you saw, what you concluded, \
and what you were unsure about."""


def decision_schema() -> dict:
    """JSON Schema for `AllocationDecision`, for backends that can constrain decoding."""
    return AllocationDecision.model_json_schema()


def _render_mandate(mandate: Mandate) -> str:
    limits = mandate.constraints
    return "\n".join(
        [
            f"Name: {mandate.name}",
            f"Objective: {mandate.objective}",
            f"Risk posture: {mandate.risk_posture}",
            f"Base asset (cash): {mandate.base_asset}",
            "",
            "HARD LIMITS — a decision breaching any of these is rejected:",
            f"- Allowed assets: {', '.join(limits.allowed_assets)}. No others, ever.",
            "- Target weights must sum to 1.0.",
            f"- No single non-cash position above {limits.max_position_pct:.0%} of the vault.",
            f"- At least {limits.min_cash_pct:.0%} must stay in {mandate.base_asset}.",
            f"- At most {limits.max_actions_per_tick} venue action(s) this tick.",
            f"- Slippage may not exceed {limits.max_slippage_bps} bps.",
            f"- Venues you may use: {', '.join(mandate.permitted_venues)}.",
        ]
    )


def _render_facts(snapshot: MarketSnapshot) -> str:
    if not snapshot.facts:
        return "No market data could be read this tick."

    rows = ["id    | kind        | subject                        | value        | source"]
    rows.append("-" * 92)
    for fact in snapshot.facts:
        subject = fact.subject
        parts = [p for p in (subject.protocol, subject.market, subject.token) if p]
        if subject.pair:
            parts.append("/".join(subject.pair))
        label = " ".join(parts) or subject.chain

        if fact.unit == "apy_fraction":
            value = f"{fact.value:.2%} APY"
        elif fact.unit == "usd":
            value = f"${fact.value:,.0f}"
        elif fact.unit == "ratio":
            value = f"{fact.value:.2%}"
        else:
            value = f"{fact.value:g} {fact.unit}"

        rows.append(f"{fact.id:<5} | {fact.kind:<11} | {label:<30} | {value:<12} | {fact.source}")
    return "\n".join(rows)


def _render_gaps(snapshot: MarketSnapshot) -> str:
    """Show the model what it could *not* see.

    A source that failed degrades the snapshot rather than crashing the loop, so
    the model has to know the difference between "utilization is fine" and
    "utilization could not be read". Hiding the gap invites a confident decision
    built on absent data.
    """
    if not snapshot.errors:
        return ""
    lines = ["", "Data you could NOT read this tick — reason about this explicitly:"]
    lines += [f"- {error.source}: {error.message}" for error in snapshot.errors]
    return "\n".join(lines)


def _render_holdings(vault: VaultState | None) -> str:
    if vault is None or not vault.holdings:
        return ""
    lines = ["", "The vault currently holds:"]
    for holding in vault.holdings:
        decimals = holding.decimals if holding.decimals is not None else 18
        amount = int(holding.balance) / (10**decimals)
        committed = (
            f" (committed to {holding.committed_to_venue})" if holding.committed_to_venue else ""
        )
        lines.append(f"- {amount:,.4f} {holding.symbol}{committed}")
    return "\n".join(lines)


def decision_messages(
    mandate: Mandate, snapshot: MarketSnapshot, vault: VaultState | None = None
) -> list[dict[str, str]]:
    """The conversation that asks for one allocation decision."""
    user = f"""\
YOUR MANDATE
{_render_mandate(mandate)}
{_render_holdings(vault)}

MARKET DATA — cite these ids in `facts_used`:
{_render_facts(snapshot)}{_render_gaps(snapshot)}

Decide what to do with this vault now.

Return exactly this JSON shape:
{{
  "action": "hold" | "rebalance" | "enter" | "exit",
  "reasoning": "what you saw, what you concluded, what you were unsure about",
  "facts_used": ["ids of the facts above that justify this"],
  "target_allocations": [{{"asset": "SYMBOL", "weight": 0.0}}],
  "venue_intents": [
    {{"venue": "uniswap", "kind": "swap", "token_in": "A", "token_out": "B",
      "pct_of_holdings": 0.0}}
  ],
  "confidence": 0.0
}}

If you choose "hold", omit `venue_intents` entirely. If you choose any other \
action, you must supply the venue intents that carry it out — an action with no \
intents changes nothing."""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
