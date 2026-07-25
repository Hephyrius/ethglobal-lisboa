"""A `VaultClient` that never touches a chain.

Used in fixture mode and whenever live mode is configured but Lane A's ABIs are
not published yet — a state that is normal during the build and must not stop the
loop from being exercised end to end.

It is honest about what it is: transaction hashes are derived from the plan's
calldata so they are stable and obviously synthetic, and `execute` still walks
every step so ordering bugs surface here rather than on a fork. What it cannot
do is prove a transaction would succeed; only the real client does that.
"""

from __future__ import annotations

import logging

from curator_schema import ExecutionPlan, Mandate, VaultState
from eth_utils import keccak

from .. import fixtures

__all__ = ["StubVaultClient"]

log = logging.getLogger(__name__)


class StubVaultClient:
    """Fixture-backed `VaultClient`."""

    name = "stub"

    async def state(self, vault: str) -> VaultState:
        return fixtures.vault_state().model_copy(update={"address": vault})

    async def execute(self, vault: str, plan: ExecutionPlan) -> list[str]:
        hashes: list[str] = []
        for index, step in enumerate(plan.steps):
            log.info("stub execute %s step %d -> %s (%s)", vault, index, step.target, step.why)
            # Derived from the step so the same plan always yields the same
            # hashes: a stable feed is easier to develop against, and a hash that
            # changes every render looks like a bug.
            digest = keccak(text=f"{vault}:{index}:{step.calldata}").hex()
            hashes.append("0x" + digest)
        return hashes

    async def deploy(self, mandate: Mandate, mandate_hash: str) -> tuple[str, str]:
        # Deterministic pseudo-address derived from the mandate hash, so the same
        # mandate always "deploys" to the same place during development.
        vault = "0x" + keccak(text=f"vault:{mandate_hash}").hex()[:40]
        tx = "0x" + keccak(text=f"deploy:{mandate_hash}").hex()
        log.info("stub deploy -> %s", vault)
        return vault, tx
