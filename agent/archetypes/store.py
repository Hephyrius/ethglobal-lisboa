"""Which vaults an archetype has already produced.

Two questions, one file per archetype under `<state_dir>/archetypes/`.

**"Have I made this one before?"** — the backstop behind *two clicks, two
different vaults*. The rotating emphasis and the nonce are what actually make
generations differ; this is what notices when they did not.

**"Which archetype made this vault?"** — nothing on-chain records it. The factory
emits no archetype, the mandate has no field for one, and `VaultFactory.vaults()`
is a flat list. Without this, a vault deployed from a card is indistinguishable
from a curated one the moment the response is gone, and Lane E cannot group them.

## Why a signature rather than the whole mandate

Two mandates that differ only in a comma of `objective` are the same strategy,
and comparing full text would call them distinct forever. The signature covers
what a depositor would call the strategy — the assets, the venues, the sources,
the posture, every numeric constraint, and the conviction — and deliberately
excludes prose. Two vaults with the same numbers and different words are the
duplicate this is looking for.

`name` is folded in separately: identical numbers under different names is still
a collision worth regenerating, but *the same name* is confusing on the dashboard
even when the numbers differ.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from curator_schema import Mandate

__all__ = ["ArchetypeStore", "Deployment", "signature"]

log = logging.getLogger(__name__)


def signature(mandate: Mandate) -> str:
    """A stable identity for *the strategy*, ignoring how it was written up."""
    constraints = mandate.constraints.model_dump(mode="json")
    payload = {
        "assets": sorted(constraints.pop("allowed_assets", [])),
        "venues": sorted(mandate.permitted_venues),
        "sources": sorted(mandate.permitted_data_sources),
        "posture": mandate.risk_posture,
        "conviction": mandate.persona.conviction if mandate.persona else None,
        "constraints": {k: constraints[k] for k in sorted(constraints)},
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Deployment:
    """One vault an archetype produced."""

    vault: str
    archetype: str
    name: str
    signature: str
    #: Which of the archetype's emphases was in force. Recorded so the rotation
    #: can be continued across a process restart rather than starting over and
    #: producing the first strategy twice.
    emphasis_index: int
    #: The wallet that asked for it, when the dApp sent one. Off-chain and
    #: asserted, exactly like Lane A's on-chain `deployer` field (§A1) — a record
    #: of who clicked, never proof.
    deployer: str | None = None


class ArchetypeStore:
    """Append-only record of archetype deployments, one JSON file per key."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir) / "archetypes"

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def deployments(self, key: str) -> list[Deployment]:
        """Everything this archetype has produced. Never raises.

        A corrupt or unreadable index costs uniqueness checking and grouping, not
        the ability to deploy — refusing to make a vault because a bookkeeping
        file is malformed would be the wrong trade for something that has no
        bearing on whether the mandate is safe.
        """
        path = self._path(key)
        if not path.exists():
            return []
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            return [Deployment(**row) for row in rows]
        except Exception as exc:  # noqa: BLE001
            log.warning("archetype index for %s is unreadable (%s); treating as empty", key, exc)
            return []

    def record(self, deployment: Deployment) -> None:
        """Append one. Never allowed to break a deploy that already happened.

        The vault exists on-chain by the time this runs, so a failure here must
        not surface as a failed deployment — that would tell the user their click
        did nothing while their vault sits deployed and unlisted.
        """
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            rows = [d.__dict__ for d in self.deployments(deployment.archetype)]
            rows.append(deployment.__dict__)
            self._path(deployment.archetype).write_text(
                json.dumps(rows, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "could not record %s under %s: %s",
                deployment.vault, deployment.archetype, exc,
            )

    def signatures(self, key: str) -> set[str]:
        return {d.signature for d in self.deployments(key)}

    def names(self, key: str) -> list[str]:
        return [d.name for d in self.deployments(key)]

    def next_emphasis_index(self, key: str, total: int) -> int:
        """Rotate rather than sample.

        Sampling would repeat an angle by chance on the second click, which is
        exactly the impression this feature cannot afford to give. Continues from
        the last recorded index so a restart does not re-run the rotation from
        the top.
        """
        if total <= 0:
            return 0
        history = self.deployments(key)
        if not history:
            return 0
        return (history[-1].emphasis_index + 1) % total

    def find(self, vault: str) -> Deployment | None:
        """Which archetype made this vault, if any. Scans every index.

        Linear over archetypes, which is three. A reverse index would be a second
        file to keep in step with this one for no measurable gain.
        """
        if not self._dir.exists():
            return None
        for path in sorted(self._dir.glob("*.json")):
            for deployment in self.deployments(path.stem):
                if deployment.vault.lower() == vault.lower():
                    return deployment
        return None
