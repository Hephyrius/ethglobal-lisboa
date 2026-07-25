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

from ...loop.idle import IDLE_FACT_ID
from ...security.untrusted import (
    FLAG,
    ID_LIMIT,
    MESSAGE_LIMIT,
    SYMBOL_LIMIT,
    UNTRUSTED_PREAMBLE,
    flagged,
    sanitize,
)

__all__ = ["SYSTEM_PROMPT", "decision_messages", "decision_schema"]

#: The source key: a registry name, not a sentence.
_SOURCE_LIMIT = 24

#: Width of the `about` column, and therefore the cap on what goes in it. The
#: two must stay equal: a value wider than the column shifts every field to its
#: right, which is the misalignment a hostile label wants.
_ABOUT_WIDTH = 32

SYSTEM_PROMPT = """\
You are the autonomous curator of an ERC-4626 vault. You allocate the vault's \
capital to pursue its mandate, and you are accountable for the outcome.

Your goal is the highest RISK-ADJUSTED return the mandate allows, which is not \
the same as the highest return. A 4% yield earned without the vault ever \
falling is worth more than a 6% yield earned through a 20% swing, because a \
depositor who withdraws during the swing takes the loss and never sees the \
recovery. Given two comparable options, prefer the steadier one; when you are \
unsure, size down rather than sizing up when you are confident.

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


def _render_persona(mandate: Mandate) -> str:
    """The persona block, or "" when the mandate has none.

    **Persona is taste; constraints are law.** The block says so in as many
    words, and that sentence is load-bearing rather than decorative: an
    "aggressive" persona that the model believes licenses a bigger position is
    an exploit wearing a style's clothing. The harness enforces the same limits
    either way — `check_decision` never sees the persona — but a model that
    thinks it has permission wastes the tick producing decisions that are
    rejected, and its `reasoning` tells a depositor it was allowed to do
    something it was not.

    Conviction steers sizing *within* `max_position_pct` and how readily the
    agent acts on a thesis. It moves no bound.
    """
    persona = mandate.persona
    if persona is None:
        return ""

    lines = [
        "",
        f"YOU ARE CURATING AS: {persona.name}.",
        f"Voice: {persona.voice}",
    ]
    if persona.biases:
        lines.append("Your leanings, which apply only when choosing between options the")
        lines.append("mandate already permits:")
        lines += [f"- {bias}" for bias in persona.biases]
    lines.append(
        {
            "low": "Conviction: low. Prefer smaller sizes and hold more readily.",
            "medium": "Conviction: medium. Size normally.",
            "high": "Conviction: high. Act on a clear thesis and size toward the upper "
            "end of what the mandate allows.",
        }[persona.conviction]
    )
    lines.append(
        "This is who you are, not what you may do. It changes which permitted "
        "option you prefer and how you write. It does not widen a single limit: "
        "you cannot reach an asset the mandate omits, exceed a cap, go under the "
        "cash floor, or accept more slippage because of who you are. The HARD "
        "LIMITS below are identical for every persona and are enforced whatever "
        "you argue."
    )
    return chr(10).join(lines)


def _render_mandate(mandate: Mandate) -> str:
    limits = mandate.constraints
    return "\n".join(
        [
            f"Name: {mandate.name}",
            f"Objective: {mandate.objective}",
            f"Risk posture: {mandate.risk_posture}",
            f"Base asset (cash): {mandate.base_asset}",
            "",
            "HARD LIMITS. A decision breaching any of these is rejected:",
            f"- Allowed assets: {', '.join(limits.allowed_assets)}. No others, ever.",
            "- Target weights must sum to 1.0.",
            f"- No single non-cash position above {limits.max_position_pct:.0%} of the vault.",
            f"- At least {limits.min_cash_pct:.0%} must stay in {mandate.base_asset}. This is "
            f"not dead weight: it is the only thing a depositor can be paid out of. The vault "
            f"cannot unwind a position to fund a withdrawal, so a holder whose shares are worth "
            f"more than the {mandate.base_asset} on hand simply cannot redeem them.",
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
    "sentiment": "market mood",
    "gas": "cost of transacting",
}

#: Only these kinds are percentage rates. Spelled out so "12.4M of liquidity"
#: cannot become "12.4% APY".
_RATE_KINDS = {"yield"}


def _format_value(fact) -> str:
    # Kind first, then unit. Two kinds share `ratio` and mean entirely different
    # things by it — a utilization of 0.78 is "78% of capacity", a sentiment of
    # 0.78 is "extreme greed" — and rendering the second as the first is exactly
    # the misread `_KIND_LABELS` exists to prevent.
    if fact.id == IDLE_FACT_ID:
        # The generic `ratio` rendering would print "68.0% of capacity", which
        # reads as the opposite of what this measures.
        return f"{fact.value:.1%} of the vault is sitting idle"
    if fact.kind == "sentiment":
        return f"{fact.value:.2f} on a 0-1 scale (0 = extreme fear, 1 = extreme greed)"
    if fact.kind == "gas":
        if fact.unit == "usd":
            return f"${fact.value:,.2f} per rebalance (dollars, not a rate)"
        return f"{fact.value:.4g} gwei (a gas price, not a rate)"

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


def _render_facts(snapshot: MarketSnapshot, marked: set[str] = frozenset()) -> str:
    """The fact table, with every third-party string fenced into its own cell.

    `about` and `source` are written by whoever deployed the pool or protocol
    they name, and `id` comes from Lane C. All three are sanitised **here**,
    at render time rather than at ingestion, so `AgentAction.snapshot` keeps the
    payload exactly as it arrived — the evidence the e2e test asserts against
    and the dApp renders as the attack.

    `marked` carries the raw values the detector objected to; they are shown
    rather than redacted, for the reason in `agent/security/untrusted.py`.
    """
    if not snapshot.facts:
        return "No market data could be read this tick."

    rows = [
        UNTRUSTED_PREAMBLE,
        "",
        "Each row states what it measures. Only rows saying 'per year' are yields.",
        "",
        f"{'id':<5} | {'measures':<20} | {'about':<{_ABOUT_WIDTH}} | {'value':<28} | source",
        "-" * 104,
    ]
    for fact in snapshot.facts:
        subject = fact.subject
        parts = [p for p in (subject.protocol, subject.market, subject.token) if p]
        legs = list(subject.pair or ())
        # Matched part by part, not against the joined string. The detector
        # reports the field it found — `protocol`, one leg of a pair — and a
        # membership test on the concatenation would silently never fire.
        hit = any(part in marked for part in (*parts, *legs))
        if legs:
            parts.append("/".join(legs))
        joined = " ".join(parts) or subject.chain
        # Cut to the *column* rather than to `sanitize`'s general label limit,
        # so a long name cannot push `value` and `source` rightward and blur one
        # row into the next. The table's shape is what a small model reads it
        # by, and the full string is in the journal for anyone who wants it.
        #
        # Not exact: the `[+N chars cut]` marker overflows by its own length,
        # because it has to be visible — silent truncation was the thing being
        # avoided. What this buys is that the overflow is *bounded and constant*
        # rather than proportional to the payload, so a 4,000-character name
        # cannot push the last two columns off the far side of the row.
        about = (
            flagged(joined, limit=_ABOUT_WIDTH - len(FLAG) - 1)
            if hit
            else sanitize(joined, limit=_ABOUT_WIDTH)
        )
        measures = _KIND_LABELS.get(fact.kind, fact.kind)

        rows.append(
            f"{sanitize(fact.id, limit=ID_LIMIT):<5} | {measures:<20} | "
            f"{about:<{_ABOUT_WIDTH}} | "
            f"{_format_value(fact):<28} | {sanitize(fact.source, limit=_SOURCE_LIMIT)}"
        )

    yields = [sanitize(f.id, limit=ID_LIMIT) for f in snapshot.facts if f.kind in _RATE_KINDS]
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

    Only genuine failures. `snapshot.notes` is rendered separately and much more
    quietly — see `_render_notes`.
    """
    if not snapshot.errors:
        return ""
    lines = ["", "Data you could NOT read this tick. Reason about this explicitly:"]
    lines += [
        f"- {sanitize(error.source, limit=_SOURCE_LIMIT)}: "
        f"{sanitize(error.message, limit=MESSAGE_LIMIT)}"
        for error in snapshot.errors
    ]
    return "\n".join(lines)


def _render_notes(snapshot: MarketSnapshot) -> str:
    """Non-failures: things a source chose not to answer, or could never answer.

    Separate from `_render_gaps` and deliberately unemphatic. These used to
    arrive in `errors[]`, which meant every tick opened by telling the agent
    that two of its four sources were broken when both were behaving exactly as
    designed — 35 of 36 journalled ticks carried "USDC is a quote token on this
    venue" under a heading that asked the model to reason about the gap.

    Worth showing at all because a curator should know why a number is absent.
    Not worth alarming it with.
    """
    if not snapshot.notes:
        return ""
    lines = ["", "Notes on your data sources. These are not failures:"]
    # Sanitised like everything else, even though this lane writes some of them
    # (`agent/security/detect.py` emits its findings here): a note that quotes
    # an attacker's label is carrying attacker text, whoever appended it.
    lines += [
        f"- {sanitize(note.source, limit=_SOURCE_LIMIT)}: "
        f"{sanitize(note.message, limit=MESSAGE_LIMIT)}"
        for note in snapshot.notes
    ]
    return "\n".join(lines)


def _render_holdings(vault: VaultState | None, marked: set[str] = frozenset()) -> str:
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

        # Every one of these is `symbol()` on an arbitrary ERC-20, read by this
        # lane's own chain client — the injection channel the wave plan's §0.3
        # does not name, and the one that renders closest to the decision.
        raw = (holding.symbol, holding.represents, holding.committed_to_venue)
        mark = flagged if any(v and v in marked for v in raw) else sanitize
        symbol = mark(holding.symbol, limit=SYMBOL_LIMIT)
        represents = mark(holding.represents, limit=SYMBOL_LIMIT)
        venue = mark(holding.committed_to_venue, limit=SYMBOL_LIMIT)

        # A receipt token has to read as its underlying, or the model sees an
        # asset its mandate never permitted and tries to "correct" a position
        # that is exactly what the mandate asked for.
        if represents:
            name = (
                f"{represents} supplied to {venue or 'a venue'} "
                f"(held as {symbol}, still counts as your {represents})"
            )
            committed = ""
        else:
            name = symbol
            committed = f" [committed to {venue}]" if venue else ""
        # The raw balance is here because an Aqua ship is denominated in base
        # units. Without it the model has to compute 0.672 WETH -> 18 decimals
        # itself, which is exactly the kind of arithmetic it gets wrong.
        lines.append(
            f"- {amount:,.6f} {name} (base units: {holding.balance}): "
            f"{valued}{committed}"
        )

    lines.append(
        "These percentages are already computed for you. Compare them directly with your "
        "target weights; do not recalculate them from the token amounts."
    )
    return "\n".join(lines)


def decision_messages(
    mandate: Mandate,
    snapshot: MarketSnapshot,
    vault: VaultState | None = None,
    reflection: str = "",
    marked: set[str] = frozenset(),
) -> list[dict[str, str]]:
    """The conversation that asks for one allocation decision.

    `reflection` is the agent's own track record, rendered by
    `agent/loop/reflection.py`. Empty when there is nothing honest to say, which
    is the normal state for a vault's first few ticks. An empty string renders
    as nothing at all rather than as a heading with no content beneath it, which
    reads as a system that lost the data.

    `marked` is the set of raw values `agent/security/detect.py` objected to.
    **Sanitisation does not depend on it** — every third-party string is fenced
    whether or not a detector ran, so a caller that forgets to pass this loses
    the annotation and keeps the protection. That asymmetry is the point: the
    load-bearing half cannot be switched off by omission.
    """
    user = f"""\
YOUR MANDATE
{_render_mandate(mandate)}
{_render_holdings(vault, marked)}
{reflection}

MARKET DATA. Cite these ids in `facts_used`:
{_render_facts(snapshot, marked)}{_render_gaps(snapshot)}{_render_notes(snapshot)}

Decide what to do with this vault now. Work in this order:

1. Read your objective above and write down the allocation it asks for.
2. Compare it with the percentages already shown under THE VAULT CURRENTLY HOLDS.
3. If they differ by more than your objective tolerates, rotate to close the gap.
4. Whether or not you rotate, look at the idle figure in the table above. \
**Capital sitting idle above the mandate's cash floor is not neutral. It is a \
position, and the position is earning nothing.** Deploying it into a permitted \
venue is the default: lending it earns yield, and posting it into Aqua earns \
fees while moving no tokens at all. **The idle figure already excludes the cash \
floor, so deploying all of it is permitted, but the floor is the entire \
withdrawal buffer: deploying right down to it leaves depositors with the bare \
minimum they can exit against.** Of two venues paying similarly, prefer the one \
you can unwind sooner.
5. Hold only if you can say why. Holding is legitimate and often right, but it \
is a choice, so `reasoning` must name the reason: the idle share is immaterial, \
the yields on offer do not cover the cost of moving, or the data you needed was \
missing. "The book is balanced" is a reason to stop rotating, not a reason to \
leave capital idle.

`target_allocations` is where you want the vault to BE, not where it already is. \
If your targets differ from the current percentages, you must supply the \
`venue_intents` that close the gap; restating the current split as a target and \
then holding is not a decision, it is a description.

Return exactly this JSON shape:
{{
  "action": "hold" | "rebalance" | "enter" | "exit",
  "reasoning": "what you saw, what you concluded, what you were unsure about",
  "facts_used": ["ids of the facts above that justify this"],
  "target_allocations": [{{"asset": "SYMBOL", "weight": 0.0}}],
  "venue_intents": [ ...one of the two shapes below... ],
  "confidence": 0.0
}}

There are four kinds of venue intent, and they do different jobs. Only the \
first one changes what the vault is exposed to; the others put an existing \
holding to work without changing the allocation at all.

To CHANGE what the vault holds, swap through Uniswap. `pct_of_holdings` is the \
fraction of the input token's holdings to sell:
{{"venue": "uniswap", "kind": "swap", "token_in": "A", "token_out": "B", \
"pct_of_holdings": 0.0}}

To EARN INTEREST on an asset the vault already holds, supply it to Aave. The \
vault receives an interest-bearing receipt token which it holds itself. This \
does NOT change your allocation - supplying USDC leaves you just as long USDC, \
it simply earns the lending rate while you hold it:
{{"venue": "aave", "kind": "supply", "asset": "A", "pct_of_holdings": 0.0}}

To GET IT BACK, withdraw. Omit `amount` to redeem the whole position:
{{"venue": "aave", "kind": "withdraw", "asset": "A"}}

To EARN FEES on what the vault already holds, post it as passive liquidity in \
Aqua. The tokens never leave the vault. Aqua records a claim against them, so \
this changes no balances and costs no slippage. `amounts` are in each token's \
smallest unit, which is the "base units" figure shown for each holding above; \
never post more than the vault holds:
{{"venue": "aqua", "kind": "ship", "tokens": ["A", "B"], \
"amounts": ["<base units of A>", "<base units of B>"], \
"program": {{"shape": "xyc", "fee_bps": 30}}}}

Idle cash earns nothing. If the book already matches your targets and a lending \
market pays a rate worth having, supplying is usually better than doing nothing \
- but check the cost of the transaction against what the extra yield earns over \
the time you expect to hold it. A few basis points of extra yield is not worth \
capturing if the trade costs more than it returns.

If you choose "hold", omit `venue_intents` entirely. If you choose any other \
action, you must supply the venue intents that carry it out. An action with no \
intents changes nothing."""

    return [
        {"role": "system", "content": SYSTEM_PROMPT + _render_persona(mandate)},
        {"role": "user", "content": user},
    ]
