"""Which Aqua positions a vault has open — the record only the harness can keep.

## Why this file has to exist

`venues/README.md` states it as an obligation on us, not a suggestion:

    **`AquaDockIntent` needs `vault.aqua_strategies[].tokens`.** `dock()` takes a
    token list that the intent does not carry, so the harness must record the
    tokens at `ship()` time. Without it, docking raises rather than guessing.

Nothing did. `VaultState.aqua_strategies` was populated nowhere in `agent/`, so
it was always `[]`, with two consequences — one visible and one not:

* The dApp's `AquaPositions` panel returns `null` on an empty list, so **an open
  Aqua position was never displayed at all**, no matter what was on chain. That
  is the symptom an operator noticed.
* **`dock()` could never be built.** `AquaVenue._tokens_for_strategy` looks the
  strategy up in `aqua_strategies` and raises when it is absent, so the agent
  could open a maker position and never close it. That is the worse half, and
  it is invisible until something tries.

## Why the position cannot be read from the chain

Aqua answers `safeBalances(maker, app, strategyHash, tokenA, tokenB)` — it can
confirm a position you can already name, but there is no enumeration. Without a
local record of *which* hashes exist, there is nothing to ask about. So the
record has to be written when the ship is submitted; it cannot be recovered
afterwards by looking.

## Where the hash comes from, and why this needs nothing from Lane D

The venue computes the hash inside `_plan_ship` and does not return it: the
`ExecutionPlan` carries it only truncated to ten characters inside prose, and
the salt it was built with comes from a private method. Rebuilding it here would
mean reaching into another lane's internals for a value it already has.

It is not necessary. **`strategy_hash` is `keccak256(strategy_bytes)`**, verified
against the live builder rather than assumed, and the strategy bytes are the
second argument of the `ship()` calldata the plan already carries. So the hash is
derivable from the plan we store anyway, using only the public
`AQUA_SHIP`/`AQUA_DOCK` signatures — no private state, no new interface.

If Lane D later surfaces the hash structurally, `_strategies_from_plan` is the
one function to change, and the store above it does not move.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from curator_schema import AquaStrategy, ExecutionPlan

__all__ = ["AquaPositionStore", "strategies_from_plan"]

log = logging.getLogger(__name__)

#: `ship(address app, bytes strategy, address[] tokens, uint256[] amounts)`
_SHIP_SELECTOR = "0x"
#: `dock(address app, bytes32 strategyHash, address[] tokens)`
_DOCK_SELECTOR = "0x"


def _selectors() -> tuple[str, str]:
    """Selectors for ship/dock, derived from Lane D's published signatures.

    Computed rather than hardcoded so a signature change upstream surfaces as
    "no positions recorded" against their own constant, instead of silently
    matching a stale four bytes forever.
    """
    from eth_utils import keccak  # type: ignore[import-untyped]

    from venues.aqua import AQUA_DOCK, AQUA_SHIP

    def selector(signature: str) -> str:
        return "0x" + keccak(text=signature)[:4].hex()

    return selector(AQUA_SHIP), selector(AQUA_DOCK)


def _decode_ship(calldata: str) -> tuple[str, list[str], str] | None:
    """`(strategy_hash, tokens, app)` from a `ship()` calldata, or None.

    Returns None rather than raising for anything that is not a ship: this runs
    over every step of every executed plan, and a Uniswap swap is not an error.
    """
    from eth_abi import decode as abi_decode  # type: ignore[import-untyped]
    from eth_utils import keccak

    ship_selector, _ = _selectors()
    if not calldata.lower().startswith(ship_selector.lower()):
        return None

    try:
        app, strategy, tokens, _amounts = abi_decode(
            ["address", "bytes", "address[]", "uint256[]"],
            bytes.fromhex(calldata[10:]),
        )
    except Exception as exc:  # noqa: BLE001 - malformed calldata is not our crash
        log.warning("could not decode an Aqua ship step: %s", exc)
        return None

    # Verified against the live builder: the hash Aqua identifies a position by
    # is exactly the keccak of the strategy bytes.
    return "0x" + keccak(strategy).hex(), [str(t) for t in tokens], str(app)


def _decode_dock(calldata: str) -> str | None:
    """The strategy hash a `dock()` closes, or None if this is not a dock."""
    from eth_abi import decode as abi_decode

    _, dock_selector = _selectors()
    if not calldata.lower().startswith(dock_selector.lower()):
        return None

    try:
        _app, strategy_hash, _tokens = abi_decode(
            ["address", "bytes32", "address[]"], bytes.fromhex(calldata[10:])
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not decode an Aqua dock step: %s", exc)
        return None
    return "0x" + strategy_hash.hex()


def strategies_from_plan(plan: ExecutionPlan) -> tuple[list[AquaStrategy], list[str]]:
    """`(opened, closed)` — what this plan ships and what it docks.

    Reads every step rather than trusting `plan.venue`, because a plan is
    submitted as one atomic `executeBatch` and the interesting steps are
    identified by their selector, not by a label on the envelope.
    """
    opened: list[AquaStrategy] = []
    closed: list[str] = []
    now = datetime.now(UTC)

    for step in plan.steps:
        shipped = _decode_ship(step.calldata)
        if shipped is not None:
            strategy_hash, tokens, app = shipped
            opened.append(
                AquaStrategy(
                    strategy_hash=strategy_hash, tokens=tokens, app=app, shipped_at=now
                )
            )
            continue

        docked = _decode_dock(step.calldata)
        if docked is not None:
            closed.append(docked)

    return opened, closed


class AquaPositionStore:
    """Open Aqua positions per vault, as one JSON file each.

    Same shape and reasoning as `MandateStore` and `PerformanceStore`: there is
    one small list per vault, it is read once per state build, and a file
    survives a restart without a database to stand up.

    Writes are atomic (temp file then `os.replace`). A half-written file would
    lose the token list, and the token list is the thing `dock()` cannot be
    built without.
    """

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir) / "aqua"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, vault: str) -> Path:
        return self._dir / f"{vault.lower()}.json"

    def read(self, vault: str) -> list[AquaStrategy]:
        path = self._path(vault)
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text())
            return [AquaStrategy.model_validate(entry) for entry in raw]
        except Exception as exc:  # noqa: BLE001 - a bad file is not a dead vault
            log.warning("could not read Aqua positions for %s: %s", vault, exc)
            return []

    def _write(self, vault: str, strategies: list[AquaStrategy]) -> None:
        path = self._path(vault)
        payload = [json.loads(s.model_dump_json()) for s in strategies]
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(tmp, path)

    def apply(self, vault: str, opened: list[AquaStrategy], closed: list[str]) -> None:
        """Record ships and forget docks, in that order.

        Deduplicated by hash: the venue derives a stable hash for the same
        program, so a retried tick that ships the same position again must not
        produce two entries for one position.
        """
        if not opened and not closed:
            return

        current = {s.strategy_hash.lower(): s for s in self.read(vault)}
        for strategy in opened:
            current[strategy.strategy_hash.lower()] = strategy
        for strategy_hash in closed:
            current.pop(strategy_hash.lower(), None)

        try:
            self._write(vault, list(current.values()))
            log.info(
                "aqua positions for %s: +%d -%d, %d open",
                vault,
                len(opened),
                len(closed),
                len(current),
            )
        except Exception as exc:  # noqa: BLE001 - never turn a good tick into a failure
            log.warning("could not record Aqua positions for %s: %s", vault, exc)
