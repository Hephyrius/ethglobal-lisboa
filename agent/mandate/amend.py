"""Agent-side mandate mutation.

A locked decision (`plans/initiate_plan.md` §2): the mandate is **mutable while
live, but only by the agent** as it pursues its objective. The human deployer
cannot change it after genesis. So this is the only path that rewrites a mandate,
and it is reachable only from inside a decision cycle.

That makes it dangerous in a specific way: an agent that can rewrite its own
constraints can rewrite away the constraints. The mandate's `update_rules` is
free text and is shown to the model, but free text cannot be *enforced* — so the
structural invariants below are checked in code, and they hold no matter what the
model asks for.

- **`base_asset` may never change.** The ERC-4626 asset is fixed at deployment,
  so a mandate naming a different one is unexecutable — and every share-price
  calculation would silently start meaning something else.
- **`base_asset` stays in `allowed_assets`.** Otherwise the vault cannot legally
  hold its own denomination and `min_cash_pct` becomes unsatisfiable.
- **`allowed_assets` may not grow beyond what the vault can price.** See below;
  this is the one that fails silently and permanently.
- **`version` is assigned here, always +1.** Left to the model it collides,
  sticks, or jumps; it is the audit trail's ordering key.
- **The result must satisfy the full `Mandate` schema.** A patch producing an
  invalid mandate is rejected whole. There is no partial application.

Anything that fails is rejected and the previous mandate stands unchanged.

## Why widening `allowed_assets` is checked in code and not left to the rule

The golden mandate's `update_rules` permit new assets *"if they have a Chainlink
Base feed"*, and that sentence became **literally true and unsafe** in the same
wave. Lane C reported (#65) that wstETH, cbETH and rETH all now have Chainlink
Base feeds — but every LST feed on Base is **18-decimal and ETH-quoted**, not the
8-decimal USD the vault assumes. Read as USD, wstETH prices at $12,399,811,032.
Lane C composes with ETH/USD in Python; `CuratedVault.totalAssets()` takes
**one** feed per token and cannot compose.

That combination is the worst failure mode this component has:

1. the model reads a rule that the asset satisfies, and amends honestly;
2. nothing downstream objects, because the amended mandate now permits it;
3. the vault buys it and `totalAssets()` cannot see it — so the vault's reported
   worth *falls by the amount spent* and the share price collapses;
4. **`priceFeed` registrations are immutable after `initialize`**, so the vault
   cannot be repaired. Only redeployment fixes it, and depositors are already in.

So the free-text rule is not the gate. The gate is `offerable_assets()` — the
same symbols-the-venue-layer-can-resolve intersection genesis offers, curated on
exactly the "verified on-chain *and* has a verified feed" basis this needs.

Two properties worth stating. **Only additions are checked**: an asset already in
the mandate stays, because a vault deployed under an older universe must remain
amendable at all. And it **fails closed** — if the venue layer cannot be imported,
`offerable_assets()` falls back to the two assets every deployment has had, and a
widening amendment is refused. Refusing to widen when pricing cannot be verified
costs a rejected amendment, which is logged and recoverable; the other direction
costs the share price, permanently.
"""

from __future__ import annotations

import logging

from curator_schema import Mandate, MandateAmendment
from pydantic import ValidationError

from .universe import offerable_assets

__all__ = ["AmendmentRejected", "apply_amendment"]

log = logging.getLogger(__name__)

#: Fields the agent may never rewrite, whatever its reasoning.
_IMMUTABLE = ("base_asset",)


class AmendmentRejected(Exception):
    """The proposed mandate change was refused. The old mandate still stands."""


def apply_amendment(current: Mandate, amendment: MandateAmendment) -> Mandate:
    """Merge `amendment.patch` over `current` and return the new mandate.

    Shallow merge, matching the frozen schema's description of `patch` as a
    partial Mandate. A nested object in the patch replaces its counterpart
    wholesale — `constraints` must therefore be supplied complete, which is
    deliberate: a deep merge would let a model relax one limit while appearing
    to restate all of them.
    """
    if not amendment.patch:
        raise AmendmentRejected("amendment carried an empty patch")

    base = current.model_dump(mode="json", exclude_none=True)

    if changed := [f for f in _IMMUTABLE if f in amendment.patch and amendment.patch[f] != base[f]]:
        raise AmendmentRejected(
            f"{', '.join(changed)} cannot be changed after genesis; the vault's "
            "on-chain asset is fixed at deployment"
        )

    if unknown := sorted(set(amendment.patch) - set(Mandate.model_fields)):
        raise AmendmentRejected(f"patch names unknown mandate field(s): {', '.join(unknown)}")

    merged = {**base, **amendment.patch}
    # Version is ours to assign, never the model's.
    merged["version"] = current.version + 1

    try:
        updated = Mandate.model_validate(merged)
    except ValidationError as exc:
        raise AmendmentRejected(f"patch produces an invalid mandate: {exc.errors()[:3]}") from exc

    if updated.base_asset not in updated.constraints.allowed_assets:
        raise AmendmentRejected(
            f"patch removes the base asset {updated.base_asset} from allowed_assets, "
            "leaving the vault unable to hold its own denomination"
        )

    # Additions only: a vault deployed under an older universe keeps whatever it
    # already names, or it could never be amended again.
    added = set(updated.constraints.allowed_assets) - set(current.constraints.allowed_assets)
    if unpriceable := sorted(added - set(offerable_assets())):
        raise AmendmentRejected(
            f"patch adds {', '.join(unpriceable)} to allowed_assets, which the vault cannot "
            f"price. A Chainlink Base feed is not sufficient — every LST feed on Base is "
            f"ETH-quoted, the vault reads one feed per token and cannot compose, and its "
            f"valuations are immutable after deployment. Buying an asset totalAssets() cannot "
            f"see makes the share price fall by the amount spent, permanently."
        )

    log.info(
        "mandate amended v%d -> v%d: %s",
        current.version,
        updated.version,
        amendment.rationale[:120],
    )
    return updated
