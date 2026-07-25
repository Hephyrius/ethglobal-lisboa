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
- **`version` is assigned here, always +1.** Left to the model it collides,
  sticks, or jumps; it is the audit trail's ordering key.
- **The result must satisfy the full `Mandate` schema.** A patch producing an
  invalid mandate is rejected whole. There is no partial application.

Anything that fails is rejected and the previous mandate stands unchanged.
"""

from __future__ import annotations

import logging

from curator_schema import Mandate, MandateAmendment
from pydantic import ValidationError

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

    log.info(
        "mandate amended v%d -> v%d: %s",
        current.version,
        updated.version,
        amendment.rationale[:120],
    )
    return updated
