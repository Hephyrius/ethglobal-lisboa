"""The decision journal — every cycle this agent has run, append-only.

One JSONL file per vault under `AGENT_STATE_DIR`. Append-only is the point: this
is the audit trail behind `GET /vault/{addr}/decisions`, and the record of what
an autonomous agent did with other people's money should not be rewritable by
the thing that wrote it.

**Rejected and failed cycles are journaled exactly like successful ones.** That
is deliberate (`packages/schema/README.md`): a curator that considered the market
and declined to act is still curating, and a decision that output validation
caught is evidence the validation layer does something. Dropping them would make
the feed a highlight reel.

Reads tolerate a corrupt line rather than failing the whole feed — a truncated
final record from a killed process should cost one entry, not the vault's entire
history.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from curator_schema import AgentAction

__all__ = ["ActionJournal"]

log = logging.getLogger(__name__)


class ActionJournal:
    """Append-only per-vault store of `AgentAction`s."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir) / "actions"

    def _path(self, vault: str) -> Path:
        return self._dir / f"{vault.lower()}.jsonl"

    def append(self, action: AgentAction) -> None:
        path = self._path(action.vault)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = action.model_dump_json(exclude_none=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _all(self, vault: str) -> list[AgentAction]:
        path = self._path(vault)
        if not path.is_file():
            return []

        actions: list[AgentAction] = []
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                actions.append(AgentAction.model_validate_json(line))
            except (ValueError, json.JSONDecodeError) as exc:
                # One unreadable record must not cost the whole history.
                log.warning("skipping unreadable journal line %s:%d (%s)", path.name, number, exc)
        return actions

    def recent(self, vault: str, limit: int = 20) -> list[AgentAction]:
        """Most recent first — the order the decision feed renders."""
        actions = self._all(vault)
        actions.sort(key=lambda a: a.timestamp, reverse=True)
        return actions[:limit]

    def count(self, vault: str) -> int:
        return len(self._all(vault))

    def last_executed(self, vault: str) -> AgentAction | None:
        """The most recent cycle that actually moved capital.

        Drives the mandate's `rebalance_cooldown_seconds`: cycles that held, were
        rejected or failed did not trade, so they must not start a cooldown.
        """
        executed = [a for a in self._all(vault) if a.status == "executed"]
        if not executed:
            return None
        return max(executed, key=lambda a: a.timestamp)
