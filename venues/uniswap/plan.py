"""Uniswap API responses → the frozen `ExecutionPlan`.

Pure translation: no network, no environment. Everything it needs arrives as
arguments, so it can be exercised against saved responses — which is how the
approval ordering and the unit conversions below stay tested without burning
live quota.

**The approval path, and why it is not the one the API suggests.** The quote
response hands back a `permitData` block to be signed as an EIP-712
`PermitSingle`. The vault cannot do that: it is a contract, it holds no key,
and the agent's key is external to it. So we take Permit2's other,
signature-free path — `Permit2.approve(token, spender, amount, expiration)`,
an ordinary call the vault can make through `execute()`. Same resulting
allowance, no signature. Verified: `POST /swap` returns 200 with no signature
supplied, so the API is content to build the calldata for this flow.

Every swap therefore emits three ordered steps:

  1. `token.approve(Permit2, amount)`      — ERC-20 allowance to Permit2
  2. `Permit2.approve(token, router, …)`   — Permit2 allowance to the router
  3. `router.execute(…)`                   — the swap calldata, verbatim

Steps 1–2 are re-emitted on every plan rather than checked first. A redundant
approve costs gas and always succeeds; a missing one reverts the entire plan.
Given the vault executes plans atomically and rarely, that trade is worth it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from curator_schema.models import ExecutionPlan, ExecutionStep

from .. import addresses
from ..abi import ERC20_APPROVE, PERMIT2_APPROVE, encode_call
from ..errors import PlanValidationError
from .client import VENUE_KEY

#: The API returns no quote expiry, so we impose one. Classic routes are priced
#: against a specific block; a minute-old route on Base (2s blocks) is ~30
#: blocks stale. Conservative on purpose — the harness refuses to submit past
#: this, and re-quoting is cheap.
QUOTE_TTL: Final[timedelta] = timedelta(seconds=45)

#: uint48 max. Permit2 treats expiration as an absolute timestamp; we bound it
#: to the quote window rather than using this, but the ceiling is needed to
#: keep the encoding in range.
_UINT48_MAX: Final[int] = (1 << 48) - 1
_UINT160_MAX: Final[int] = (1 << 160) - 1

#: How long the Permit2 allowance stays live. Long enough that a slow block
#: does not invalidate the plan mid-execution, short enough that a stale
#: allowance is not left standing against a vault holding user funds.
PERMIT2_ALLOWANCE_TTL: Final[timedelta] = timedelta(minutes=30)


def _to_int(value: Any) -> int:
    """API integers arrive as decimal strings, hex strings (`value: "0x00"`) or
    ints depending on the field. Normalise all three."""
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text, 16) if text.startswith("0x") else int(text)


def _token_meta(quote: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Symbol/decimals per token address, harvested from the route the API
    already returned — saves an on-chain lookup for the human-readable summary."""
    meta: dict[str, dict[str, Any]] = {}
    for leg in quote.get("route") or []:
        for hop in leg:
            for side in ("tokenIn", "tokenOut"):
                token = hop.get(side)
                if token and token.get("address"):
                    meta[token["address"].lower()] = token
    return meta


def _format_amount(raw: int, decimals: int | None) -> str:
    if decimals is None:
        return str(raw)
    scaled = raw / (10**decimals)
    return f"{scaled:,.6f}".rstrip("0").rstrip(".")


def describe(quote: dict[str, Any]) -> str:
    """Plain-language summary for the decision feed. Best-effort — a missing
    field degrades the sentence, never raises."""
    meta = _token_meta(quote)
    try:
        source, dest = quote["input"], quote["output"]
        in_meta = meta.get(source["token"].lower(), {})
        out_meta = meta.get(dest["token"].lower(), {})
        in_dec = int(in_meta["decimals"]) if in_meta.get("decimals") else None
        out_dec = int(out_meta["decimals"]) if out_meta.get("decimals") else None
        return (
            f"swap {_format_amount(_to_int(source['amount']), in_dec)} "
            f"{in_meta.get('symbol', 'tokens')} for "
            f"~{_format_amount(_to_int(dest['amount']), out_dec)} "
            f"{out_meta.get('symbol', 'tokens')}"
        )
    except (KeyError, TypeError, ValueError):
        return "swap via Uniswap"


def slippage_bps(quote: dict[str, Any]) -> int | None:
    """`quote.slippage` is a PERCENT float (2.5 means 2.5%). The mandate ceiling
    it gets compared against is in basis points, so convert here — the one place
    that knows the API's unit."""
    raw = quote.get("slippage")
    if raw is None:
        return None
    try:
        return max(0, round(float(raw) * 100))
    except (TypeError, ValueError):
        return None


def build_plan(
    quote_response: dict[str, Any],
    swap_response: dict[str, Any],
    *,
    now: datetime | None = None,
    include_approvals: bool = True,
) -> ExecutionPlan:
    """Assemble the three-step plan.

    `now` is injectable so the time-dependent fields are deterministic in tests.
    `include_approvals=False` drops steps 1–2 for a vault with standing
    allowances — off by default, because a missing approval reverts the plan.
    """
    now = now or datetime.now(UTC)
    quote = quote_response.get("quote") or {}
    swap = swap_response.get("swap") or {}

    for field in ("to", "data"):
        if not swap.get(field):
            raise PlanValidationError(
                f"Uniswap /swap response has no `{field}`; cannot build a plan"
            )

    token_in = quote["input"]["token"]
    amount_in = _to_int(quote["input"]["maximumAmount"] or quote["input"]["amount"])
    router = swap["to"]

    steps: list[ExecutionStep] = []

    if include_approvals:
        expiration = min(
            int((now + PERMIT2_ALLOWANCE_TTL).timestamp()), _UINT48_MAX
        )
        steps.append(
            ExecutionStep(
                target=token_in,
                value="0",
                calldata=encode_call(ERC20_APPROVE, addresses.PERMIT2, amount_in),
                why=f"approve Permit2 to move {amount_in} of {token_in[:10]}…",
            )
        )
        steps.append(
            ExecutionStep(
                target=addresses.PERMIT2,
                value="0",
                calldata=encode_call(
                    PERMIT2_APPROVE,
                    token_in,
                    router,
                    min(amount_in, _UINT160_MAX),
                    expiration,
                ),
                why="grant the Uniswap router a Permit2 allowance (no signature needed)",
            )
        )

    steps.append(
        ExecutionStep(
            target=router,
            value=str(_to_int(swap.get("value", 0))),
            calldata=swap["data"],
            why=describe(quote),
        )
    )

    plan = ExecutionPlan(
        venue=VENUE_KEY,
        steps=steps,
        expected_effect=describe(quote),
        expected_slippage_bps=slippage_bps(quote),
        quote_expires_at=now + QUOTE_TTL,
    )
    assert_targets_allowlisted(plan)
    return plan


def assert_targets_allowlisted(plan: ExecutionPlan) -> None:
    """Fail here, with the seam named, rather than as an opaque on-chain revert.

    This checks against `addresses.EXPECTED_ALLOWLIST` — what we have ASKED
    Lane A to allowlist, not what the deployed vault actually enforces. Lane D
    never reads `contracts/`, so it cannot check the real thing; this catches
    the common case where an adapter invents a target nobody agreed to.
    """
    for index, step in enumerate(plan.steps):
        if step.target.lower() not in addresses.EXPECTED_ALLOWLIST:
            raise PlanValidationError(
                f"step {index} targets {step.target}, which is not on the vault "
                f"allowlist agreed with Lane A. Either the API returned a new "
                f"contract or the allowlist needs extending — see cross-lane "
                f"requests 7 and 8 in docs/active-work.md."
            )
