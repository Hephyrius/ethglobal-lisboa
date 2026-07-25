"""Which assets a new vault may actually be given.

## Why this is not just a list

`Mandate.constraints.allowed_assets` is user-authored during genesis, and the
genesis model will happily offer whatever sounds plausible. Two independent
things have to be true of an asset before a vault can hold it, and a mandate
that names one without both produces a vault that is broken in a way nobody
notices until it trades:

1. **A venue adapter can resolve the symbol to an address.** Otherwise every
   swap intent naming it fails at plan time with `UnknownTokenError` — the
   agent proposes, the harness rejects, forever.
2. **The vault can price it.** `CuratedVault.totalAssets()` values non-base
   holdings through registered Chainlink feeds, and those valuations are
   **immutable after `initialize`**. An asset with no registered feed is
   invisible to `totalAssets()`, so buying it makes the vault's reported worth
   *fall by the amount spent* and the share price collapses.

The second is the dangerous one, because it fails silently and in the direction
of losing depositors money on paper.

So the offerable set is the intersection: symbols the venue layer can resolve.
`venues/addresses.py` is already curated on exactly that basis — every token in
it was verified on-chain and has a verified Chainlink feed — which makes it the
right single source rather than a second list that can drift from the first.

The base asset is included; a mandate naming USDC as both base asset and an
allowed asset is normal and correct.
"""

from __future__ import annotations

import logging

__all__ = ["offerable_assets"]

log = logging.getLogger(__name__)

#: What to offer if the venue layer cannot be imported. Deliberately the two
#: assets every deployment has had since Wave 0 — a fallback that offers more
#: than the deployment supports is worse than one that offers less.
_FALLBACK = ("USDC", "WETH")


def offerable_assets() -> list[str]:
    """Symbols a genesis mandate may name in `allowed_assets`.

    Read from the venue token table rather than hardcoded, so widening the
    universe stays a one-file edit. Aliases that resolve to an address already
    listed under its canonical symbol are dropped — offering both "ETH" and
    "WETH" invites a mandate that names them as two positions when the vault
    holds one balance.
    """
    try:
        from venues.addresses import TOKENS
    except Exception as exc:  # noqa: BLE001 - genesis must work without the venue lane
        log.warning("venue token table unavailable (%s); offering %s", exc, _FALLBACK)
        return list(_FALLBACK)

    seen: dict[str, str] = {}
    for symbol, address in TOKENS.items():
        seen.setdefault(address.lower(), symbol)

    # Order by the token table's own order, which puts the base asset first and
    # reads as a sensible menu rather than an alphabetised one.
    canonical = set(seen.values())
    return [symbol for symbol in TOKENS if symbol in canonical]
