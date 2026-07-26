"""Which deployment manifest this process is talking about.

`deployments/base-fork.json` was hardcoded in eight places across four lanes.
That was correct while one network existed and becomes a silent, expensive bug
the moment a second one does: a process pointed at Base mainnet would read a
factory address from the fork, find no bytecode there, and report an empty
portfolio, no vaults and no peers — with every seam claiming to be live. Nothing
in the response distinguishes "this vault has no positions" from "you are
reading the wrong chain's address book".

Resolution order, most explicit first:

1. ``DEPLOYMENTS_FILE`` — an exact path. Already the contract `venues/` honours
   (`venues/addresses.py`), so this keeps one env var meaning one thing
   everywhere rather than inventing a second.
2. ``DEPLOY_NETWORK`` — the same variable `Deploy.s.sol` uses to decide which
   file to *write*, so reader and writer cannot disagree about the name.
3. ``deployments/base-fork.json`` — the local default, so a fresh clone and the
   whole existing test suite behave exactly as before.

**A missing manifest is not an error here.** The file legitimately does not
exist before the first deploy, and several callers already treat absence as
"nothing deployed yet". This module resolves a path; it does not read one.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["REPO_ROOT", "deployments_dir", "deployments_path", "network_name"]

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Matches `Deploy.s.sol`, which defaults `DEPLOY_NETWORK` to `base-fork` and
#: treats anything it does not recognise as a real network — so a typo fails
#: safe there. Here a typo yields a path that does not exist, which surfaces as
#: "nothing deployed" rather than as wrong addresses. Both fail safe; neither
#: silently uses the fork's.
DEFAULT_NETWORK = "base-fork"


def deployments_dir() -> Path:
    return REPO_ROOT / "deployments"


def network_name() -> str:
    """The deployment this process considers current."""
    return os.environ.get("DEPLOY_NETWORK") or DEFAULT_NETWORK


def deployments_path() -> Path:
    """Path to the manifest. May not exist — callers already handle that."""
    override = os.environ.get("DEPLOYMENTS_FILE")
    if override:
        return Path(override)
    return deployments_dir() / f"{network_name()}.json"
