"""Loading Lane A's published ABIs.

`contracts/out/` is committed on purpose — it is how Lane A publishes its
interface to every other lane (`docs/active-work.md`). Reading the compiled
artifact is therefore the *correct* integration surface, and the reason this lane
never opens `contracts/src/`: the ABI is the contract, the Solidity is Lane A's
business.

If an artifact is missing — Lane A mid-recompile, a fresh clone before the first
`forge build` — the minimal fallback below keeps the harness importable and the
tests running. It carries only what the harness actually calls, and it is a
floor, not a substitute: whenever the real artifact exists it wins.
"""

from __future__ import annotations

import json
import logging
from functools import cache
from typing import Any

from ..config import REPO_ROOT

__all__ = ["load_abi", "ERC20_ABI", "artifact_path"]

log = logging.getLogger(__name__)

_OUT_DIR = REPO_ROOT / "contracts" / "out"

#: Only what this lane calls: balances and metadata for holdings display.
ERC20_ABI: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "symbol",
        "inputs": [],
        "outputs": [{"type": "string"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "decimals",
        "inputs": [],
        "outputs": [{"type": "uint8"}],
        "stateMutability": "view",
    },
    {
        "type": "function",
        "name": "balanceOf",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"type": "uint256"}],
        "stateMutability": "view",
    },
]

#: Enough of Lane A's surface to read a vault and submit a plan. Matches the
#: published artifact; kept only so the harness works before `forge build`.
_FALLBACK: dict[str, list[dict[str, Any]]] = {
    "CuratedVault": [
        {"type": "function", "name": n, "inputs": [], "outputs": [{"type": t}],
         "stateMutability": "view"}
        for n, t in [
            ("asset", "address"),
            ("totalAssets", "uint256"),
            ("totalSupply", "uint256"),
            ("decimals", "uint8"),
            ("agent", "address"),
            ("mandateHash", "bytes32"),
        ]
    ]
    + [
        {
            "type": "function",
            "name": "holdings",
            "inputs": [],
            "outputs": [
                {
                    "type": "tuple[]",
                    "components": [
                        {"name": "token", "type": "address"},
                        {"name": "decimals", "type": "uint8"},
                        {"name": "balance", "type": "uint256"},
                        {"name": "valueInAsset", "type": "uint256"},
                    ],
                }
            ],
            "stateMutability": "view",
        },
        {
            "type": "function",
            "name": "executeBatch",
            "inputs": [
                {
                    "name": "calls",
                    "type": "tuple[]",
                    "components": [
                        {"name": "target", "type": "address"},
                        {"name": "value", "type": "uint256"},
                        {"name": "data", "type": "bytes"},
                    ],
                }
            ],
            "outputs": [{"name": "results", "type": "bytes[]"}],
            "stateMutability": "nonpayable",
        },
    ],
    "VaultFactory": [
        {
            "type": "function",
            "name": "createVault",
            "inputs": [
                {
                    "name": "params",
                    "type": "tuple",
                    "components": [
                        {"name": "asset", "type": "address"},
                        {"name": "name", "type": "string"},
                        {"name": "symbol", "type": "string"},
                        {"name": "agent", "type": "address"},
                        {"name": "guardian", "type": "address"},
                        {"name": "mandateHash", "type": "bytes32"},
                    ],
                }
            ],
            "outputs": [{"name": "vault", "type": "address"}],
            "stateMutability": "nonpayable",
        },
        {
            "type": "event",
            "name": "VaultCreated",
            "inputs": [
                {"name": "vault", "type": "address", "indexed": True},
                {"name": "asset", "type": "address", "indexed": True},
                {"name": "agent", "type": "address", "indexed": True},
                {"name": "mandateHash", "type": "bytes32", "indexed": False},
            ],
            "anonymous": False,
        },
    ],
}


def artifact_path(name: str):
    return _OUT_DIR / f"{name}.sol" / f"{name}.json"


@cache
def load_abi(name: str) -> list[dict[str, Any]]:
    """Lane A's ABI for `name`, or the minimal fallback."""
    path = artifact_path(name)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))["abi"]
        except (KeyError, ValueError) as exc:
            log.warning("could not read %s (%s); using the fallback ABI", path, exc)
    else:
        log.warning("%s not found; using the fallback ABI. Has Lane A run `forge build`?", path)

    if name not in _FALLBACK:
        raise FileNotFoundError(f"no artifact and no fallback ABI for {name}")
    return _FALLBACK[name]
