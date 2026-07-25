"""The share-price series — append-only, one JSONL file per vault.

Deliberately the same shape as `agent/loop/store.py`: JSONL under
`AGENT_STATE_DIR`, append-only, tolerant of a corrupt final line. A vault's
performance record and its decision record are the same kind of artifact — the
evidence of what an autonomous agent did with other people's money — and
neither should be rewritable by the thing that writes it.

## Why this exists at all

Nothing in the system recorded what a share was worth an hour ago. `AgentAction`
carries a `MarketSnapshot` and an `ExecutionPlan` but no `VaultState`, so the
36-action journal could not be mined for a price history either. The vault page
could show what the agent *decided* and never whether it *worked*.

## De-duplication

The same block is written at most once. Ticks, the sampler and the backfill all
observe the same chain, and on a pinned fork a quiet minute produces no new
block — so without this the series fills with identical points and every
volatility figure computed from it is wrong in a way that looks plausible.

Points are keyed on `block_number` where a vault client supplied one, and fall
back to the timestamp otherwise.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from curator_schema import PerformancePoint

__all__ = ["PerformanceStore"]

log = logging.getLogger(__name__)


class PerformanceStore:
    """Append-only per-vault store of `PerformancePoint`s."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir) / "performance"

    def _path(self, vault: str) -> Path:
        return self._dir / f"{vault.lower()}.jsonl"

    # ── writes ────────────────────────────────────────────────────────────

    def append(self, vault: str, point: PerformancePoint) -> bool:
        """Record one observation. Returns False if it was a duplicate.

        The caller is told rather than silently succeeding, because "we already
        had this block" and "we recorded a new observation" mean different
        things to a sampler deciding how often to poll.
        """
        if self._already_have(vault, point):
            return False

        path = self._path(vault)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(point.model_dump_json(exclude_none=True) + "\n")
        return True

    def extend(self, vault: str, points: list[PerformancePoint]) -> int:
        """Append many, skipping duplicates. Returns how many were new.

        Used by the backfill, which produces its points oldest-first and would
        otherwise re-read the whole file once per point.
        """
        if not points:
            return 0

        seen = {self._key(p) for p in self.read(vault)}
        fresh = []
        for point in points:
            key = self._key(point)
            if key in seen:
                continue
            seen.add(key)
            fresh.append(point)

        if not fresh:
            return 0

        path = self._path(vault)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for point in fresh:
                handle.write(point.model_dump_json(exclude_none=True) + "\n")
        return len(fresh)

    # ── reads ─────────────────────────────────────────────────────────────

    def read(self, vault: str) -> list[PerformancePoint]:
        """Every readable point, oldest first — the order a chart plots.

        Sorted on read rather than trusting file order: the backfill appends
        historical points after live ones already exist, so the file is not
        chronological and a chart drawn from raw file order would zig-zag.
        """
        path = self._path(vault)
        if not path.is_file():
            return []

        points: list[PerformancePoint] = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                points.append(PerformancePoint.model_validate_json(line))
            except (ValueError, json.JSONDecodeError) as exc:
                # One unreadable record costs one point, never the whole curve.
                log.warning("skipping unreadable point %s:%d (%s)", path.name, number, exc)
        points.sort(key=lambda p: p.timestamp)
        return points

    def vaults(self) -> list[str]:
        """Every vault with a recorded series."""
        if not self._dir.is_dir():
            return []
        return sorted(p.stem for p in self._dir.glob("*.jsonl"))

    # ── de-duplication ────────────────────────────────────────────────────

    @staticmethod
    def _key(point: PerformancePoint) -> str:
        if point.block_number is not None:
            return f"b{point.block_number}"
        return f"t{point.timestamp.isoformat()}"

    def _already_have(self, vault: str, point: PerformancePoint) -> bool:
        """Scan for the key without parsing every record.

        A substring test on the raw line, not a full parse: this runs on every
        tick and the file grows without bound, and the honest tradeoff is that
        a false positive would only ever *skip* a duplicate-looking point.
        The key is distinctive enough (`"block_number":123456`) that a
        collision would need the number to appear in another field entirely.
        """
        path = self._path(vault)
        if not path.is_file():
            return False

        if point.block_number is not None:
            needle = f'"block_number":{point.block_number}'
        else:
            needle = f'"timestamp":"{point.timestamp.isoformat()}'

        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return any(needle in line for line in handle)
