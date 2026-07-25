"""Where a vault's mandate lives between ticks.

One JSON file per vault under `AGENT_STATE_DIR`. That is the right amount of
machinery here: there is exactly one mandate per vault (locked decision — one
agent per vault), it is read once per tick, and a file on disk survives a restart
without a database to stand up on the macOS box at 10:00.

The mandate is written at genesis and thereafter **only the agent may change it**
(`plans/initiate_plan.md` §2). Nothing in this module is reachable from an HTTP
route that a human drives; amendments go through `agent/mandate/amend.py`, which
is called from inside the decision cycle.

Writes are atomic — serialize to a temporary file in the same directory, then
`os.replace`. A half-written mandate would be unrecoverable: the agent could not
load it and no human is permitted to fix it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from curator_schema import Mandate

from .hashing import mandate_hash

__all__ = ["MandateStore", "MandateNotFound"]

log = logging.getLogger(__name__)


class MandateNotFound(LookupError):
    """No mandate is stored for this vault."""


class MandateStore:
    """Per-vault mandate persistence."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir) / "mandates"

    def _path(self, vault: str) -> Path:
        # Addresses are case-insensitive on-chain but case-sensitive on disk, and
        # a checksummed address from the dApp must find the file written from a
        # lowercased one.
        return self._dir / f"{vault.lower()}.json"

    def exists(self, vault: str) -> bool:
        return self._path(vault).is_file()

    def load(self, vault: str) -> Mandate:
        path = self._path(vault)
        if not path.is_file():
            raise MandateNotFound(
                f"no mandate stored for {vault}; it is written at genesis by "
                "POST /genesis/finalize"
            )
        return Mandate.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, vault: str, mandate: Mandate) -> str:
        """Persist and return the mandate hash."""
        path = self._path(vault)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = mandate.model_dump_json(exclude_none=True, indent=2)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, path)

        digest = mandate_hash(mandate)
        log.info("mandate v%d saved for %s (%s)", mandate.version, vault, digest[:10])
        return digest

    def vaults(self) -> list[str]:
        """Every vault this harness has a mandate for."""
        if not self._dir.is_dir():
            return []
        return sorted(p.stem for p in self._dir.glob("*.json"))
