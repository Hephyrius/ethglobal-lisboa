"""Loading Lane A's published ABIs.

Lane A publishes its interface two ways, and asks consumers to prefer the first
(cross-lane request #2): `contracts/abis/<Name>.json` is a **flat ABI array**
curated for exactly this purpose, while `contracts/out/<Name>.sol/<Name>.json` is
the raw Foundry artifact with the ABI nested under `.abi`. Both are committed on
purpose. Reading either is the *correct* integration surface, and the reason this
lane never opens `contracts/src/`: the ABI is the contract, the Solidity is
Lane A's business.

So the lookup order is: the curated flat array, then the raw artifact, then a
minimal built-in fallback carrying only what the harness actually calls. The
fallback exists so a fresh clone before the first `forge build`, or a mid-
recompile moment, still imports and still runs the tests — it is a floor, never a
substitute. Whenever Lane A's real ABI is present, it wins.
"""

from __future__ import annotations

import json
import logging
from functools import cache
from typing import Any

from ..config import REPO_ROOT

__all__ = ["load_abi", "ERC20_ABI", "artifact_path"]

log = logging.getLogger(__name__)

#: Lane A's curated flat ABI arrays — the interface they ask consumers to use.
_ABI_DIR = REPO_ROOT / "contracts" / "abis"
#: Raw Foundry artifacts, ABI nested under `.abi`.
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
    """The raw Foundry artifact. `abi_path` is the preferred source."""
    return _OUT_DIR / f"{name}.sol" / f"{name}.json"


def abi_path(name: str):
    """Lane A's curated flat ABI array."""
    return _ABI_DIR / f"{name}.json"


def _read_flat(name: str) -> list[dict[str, Any]] | None:
    path = abi_path(name)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        log.warning("could not parse %s (%s)", path, exc)
        return None
    # Tolerate the file being an artifact rather than a flat array: Lane A
    # documents it as flat, but guessing wrong here would silently fall through
    # to the minimal ABI and lose every function the harness needs.
    if isinstance(loaded, list):
        return loaded
    if isinstance(loaded, dict) and isinstance(loaded.get("abi"), list):
        return loaded["abi"]
    log.warning("%s is neither a flat ABI array nor an artifact", path)
    return None


def _read_artifact(name: str) -> list[dict[str, Any]] | None:
    path = artifact_path(name)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))["abi"]
    except (KeyError, ValueError) as exc:
        log.warning("could not read %s (%s)", path, exc)
        return None


@cache
def load_abi(name: str) -> list[dict[str, Any]]:
    """Lane A's ABI for `name`, preferring their curated flat array."""
    if (abi := _read_flat(name)) is not None:
        return abi
    if (abi := _read_artifact(name)) is not None:
        log.info("%s: using the raw Foundry artifact (no flat ABI published)", name)
        return abi

    log.warning(
        "no published ABI for %s in %s or %s; using the minimal fallback. "
        "Has Lane A run `forge build`?",
        name,
        _ABI_DIR,
        _OUT_DIR,
    )
    if name not in _FALLBACK:
        raise FileNotFoundError(f"no published ABI and no fallback for {name}")
    return _FALLBACK[name]
