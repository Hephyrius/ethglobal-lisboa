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


#: What each fact kind actually measures, in words the model cannot mistake for
#: something else. Observed failure: a 3B model read `f6 | liquidity | uniswap-v3
#: USDC/WETH | $12,400,000` and reported it as "the highest headline APY of
#: 10.43%" — citing a real fact id while inventing its value and its meaning.
#: Grounding validation catches invented *ids*, not invented *numbers*, so the
#: defence has to be that the row cannot be misread in the first place.
_KIND_LABELS = {
    "yield": "lending yield",
    "price": "spot price",
    "tvl": "total value locked",
    "liquidity": "pool depth",
    "volatility": "realized volatility",
    "utilization": "utilization",
    "volume": "traded volume",
}

#: Only these kinds are percentage rates. Spelled out so "12.4M of liquidity"
#: cannot become "12.4% APY".
_RATE_KINDS = {"yield"}


def _format_value(fact) -> str:
    if fact.unit == "apy_fraction":
        return f"{fact.value:.2%} per year"
    if fact.unit == "usd":
        if abs(fact.value) >= 1_000_000:
            return f"${fact.value / 1_000_000:,.1f}M (dollars, not a rate)"
        return f"${fact.value:,.0f} (dollars, not a rate)"
    if fact.unit == "ratio":
        return f"{fact.value:.1%} of capacity"
    if fact.unit == "bps":
        return f"{fact.value:g} bps"
    return f"{fact.value:g} {fact.unit}"


def _render_facts(snapshot: MarketSnapshot) -> str:
    if not snapshot.facts:
        return "No market data could be read this tick."

    rows = [
        "Each row states what it measures. Only rows saying 'per year' are yields.",
        "",
        f"{'id':<5} | {'measures':<20} | {'about':<28} | {'value':<28} | source",
        "-" * 100,
    ]
    for fact in snapshot.facts:
        subject = fact.subject
        parts = [p for p in (subject.protocol, subject.market, subject.token) if p]
        if subject.pair:
            parts.append("/".join(subject.pair))
        about = " ".join(parts) or subject.chain
        measures = _KIND_LABELS.get(fact.kind, fact.kind)

        rows.append(
            f"{fact.id:<5} | {measures:<20} | {about:<28} | "
            f"{_format_value(fact):<28} | {fact.source}"
        )

    yields = [f.id for f in snapshot.facts if f.kind in _RATE_KINDS]
    rows.append("")
    rows.append(
        f"Yields available this tick: {', '.join(yields) if yields else 'none'}. "
        "No other row is a yield. Do not describe one as an APY."
    )
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
    """Current holdings **with their weights already computed.**

    Observed failure, and the reason this does the arithmetic rather than the
    model: given `1,750.0000 USDC` and `0.4034 WETH`, a 3B model reported *"403.4
    WETH, which is a 23.1% allocation (0.4034 / 1750 * 100)"* — a misread
    magnitude, a division across two different units, and a wrong answer, from
    which it concluded the book was balanced and declined to rebalance. The true
    split was about 70/30.

    Weighing a portfolio needs a price, and asking a small model to apply one to
    raw token amounts is asking for exactly that. The vault already values every
    holding through the same Chainlink feed `totalAssets()` uses, and it crosses
    the wire on `Holding.value_in_asset` — so the weights are given, in the same
    units the mandate expresses targets in, and the model only has to compare
    numbers to numbers.
    """
    if vault is None or not vault.holdings:
        return ""

    total = int(vault.total_assets or 0)
    scale = 10**vault.asset_decimals
    lines = [
        "",
        f"THE VAULT CURRENTLY HOLDS. Total value {total / scale:,.2f} in base asset units:",
    ]

    for holding in vault.holdings:
        decimals = holding.decimals if holding.decimals is not None else 18
        amount = int(holding.balance) / (10**decimals)

        if holding.value_in_asset is not None and total > 0:
            value = int(holding.value_in_asset)
            weight = f"{value / total:.1%} of the vault"
            valued = f"worth {value / scale:,.2f}, {weight}"
        else:
            valued = "value unknown this tick"

        committed = (
            f" [committed to {holding.committed_to_venue}]" if holding.committed_to_venue else ""
        )
        lines.append(f"- {amount:,.6f} {holding.symbol}: {valued}{committed}")

    lines.append(
        "These percentages are already computed for you. Compare them directly with your "
        "target weights; do not recalculate them from the token amounts."
    )
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
