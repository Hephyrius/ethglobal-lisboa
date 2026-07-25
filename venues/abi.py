"""Minimal ABI encoding — build one call's calldata, nothing more.

Scoped this narrowly on purpose. Every adapter in this lane needs "function
signature + args → 0x hex calldata" and none of them need contract objects,
transaction signing, or a node connection, so this stays a pure function over
`eth_abi` rather than becoming the lane's grab-bag (INSTRUCTIONS.md Rule 6).
"""

from __future__ import annotations

import re
from typing import Any, Final

from eth_abi import encode as abi_encode
from eth_utils import keccak

_SIGNATURE: Final[re.Pattern[str]] = re.compile(r"^(?P<name>\w+)\((?P<args>.*)\)$")


def selector(signature: str) -> bytes:
    """First 4 bytes of keccak256 of a canonical signature.

    `signature` must be canonical — `approve(address,uint256)`, no spaces, no
    parameter names — because keccak of a cosmetically different string is a
    different, silently wrong selector.
    """
    return keccak(text=signature)[:4]


def _arg_types(signature: str) -> list[str]:
    match = _SIGNATURE.match(signature)
    if not match:
        raise ValueError(f"not a canonical function signature: {signature!r}")
    args = match.group("args").strip()
    return [a.strip() for a in args.split(",")] if args else []


def encode_call(signature: str, *args: Any) -> str:
    """`encode_call("approve(address,uint256)", spender, amount)` → `"0x…"`.

    Addresses may be passed as hex strings; eth_abi wants them checksummed or
    lowercase but is unhappy with mixed junk, so they are normalised here.
    """
    types = _arg_types(signature)
    if len(types) != len(args):
        raise ValueError(
            f"{signature} takes {len(types)} argument(s), got {len(args)}"
        )
    normalised = [
        a.lower() if t == "address" and isinstance(a, str) else a
        for t, a in zip(types, args, strict=True)
    ]
    return "0x" + (selector(signature) + abi_encode(types, normalised)).hex()


def encode_args(types: list[str], args: list[Any]) -> bytes:
    """Bare ABI encoding with no selector — for nested `bytes` payloads."""
    return abi_encode(types, args)


# ── Signatures used by this lane ──────────────────────────────────────────
# Kept together so a typo is visible in one place rather than inline at three
# call sites. Each is the canonical form; do not reformat.

ERC20_APPROVE: Final[str] = "approve(address,uint256)"

#: Permit2 AllowanceTransfer.approve — the signature-free path. This is what
#: makes the vault workable as a swapper: it is a contract with no key of its
#: own, so it cannot produce the EIP-712 PermitSingle signature the API's
#: `permitData` block expects. Calling Permit2.approve directly achieves the
#: same allowance with an ordinary transaction the vault CAN make.
PERMIT2_APPROVE: Final[str] = "approve(address,address,uint160,uint48)"

#: Uniswap UniversalRouter. We never encode this ourselves — the Trading API
#: returns the calldata pre-built. Recorded here only so the selector can be
#: asserted against what the API sent, which is how a swapped-in wrong endpoint
#: would be caught.
UNIVERSAL_ROUTER_EXECUTE: Final[str] = "execute(bytes,bytes[],uint256)"
