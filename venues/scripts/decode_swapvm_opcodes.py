"""Name the instruction behind every opcode of the *deployed* SwapVM.

`venues/aqua/solidity/test/SwapVMOpcodeTable.t.sol` ships a one-instruction
program `[i, 0]` for each candidate opcode `i` and records what the deployed VM
does with it. Almost every instruction parses its arguments first and reverts
with an error naming itself, so the revert selector identifies the instruction.

This script turns those selectors into names. It computes them from the swap-vm
and aqua **sources** rather than from a hand-typed table, because a hand-typed
selector is a guess with four bytes of confidence behind it, and a wrong opcode
is a silently mispriced position — the one failure mode worse than no position
at all.

    uv run python venues/scripts/decode_swapvm_opcodes.py            # print the table
    uv run python venues/scripts/decode_swapvm_opcodes.py 0x2087efa1 # look one up

Requires the Solidity dependencies to be installed
(`venues/aqua/solidity/node_modules/`, via `pnpm install --ignore-workspace`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from eth_utils import keccak

#: Root of the installed 1inch Solidity sources.
SOLIDITY = Path(__file__).resolve().parents[1] / "aqua" / "solidity" / "node_modules" / "@1inch"

#: `error Name(type name, type name);` — possibly spanning lines.
_ERROR = re.compile(r"\berror\s+(\w+)\s*\(([^)]*)\)\s*;", re.MULTILINE | re.DOTALL)

#: Selectors that are not custom errors and so are never found in the sources.
_BUILTIN: dict[str, str] = {
    "0x4e487b71": "Panic(uint256) — Solidity builtin. At an opcode index this is "
    "panic 0x32, array out-of-bounds: the index is past the end of the "
    "deployed instruction table.",
    "0x08c379a0": "Error(string) — Solidity builtin `require` with a reason string.",
}


def _canonical(params: str) -> str:
    """`(uint256 amountIn, address to)` → `uint256,address`.

    Only the types enter the selector preimage. Argument names, whitespace and
    trailing commas do not, and getting that wrong yields a plausible-looking
    selector that matches nothing.
    """
    types: list[str] = []
    for part in params.split(","):
        part = part.strip()
        if not part:
            continue
        # The type is the first token; anything after it is a name or location.
        types.append(part.split()[0])
    return ",".join(types)


def error_selectors() -> dict[str, list[str]]:
    """Selector → signatures declaring it, across every installed 1inch source.

    A list rather than a single name because Solidity permits the same error to
    be declared in several contracts (swap-vm declares `FeeBpsOutOfRange` three
    times), and collapsing that to one name would hide the ambiguity.
    """
    found: dict[str, list[str]] = {}
    if not SOLIDITY.is_dir():
        raise SystemExit(
            f"1inch sources not found at {SOLIDITY}.\n"
            "Run: cd venues/aqua/solidity && pnpm install --ignore-workspace"
        )

    for path in sorted(SOLIDITY.rglob("*.sol")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # pnpm stores dependencies as junctions into a content-addressed
            # store, and some resolve to entries this process cannot open. They
            # are typechain artifacts, never instruction sources — skipping one
            # cannot lose an error declaration that matters here.
            continue
        for name, params in _ERROR.findall(text):
            signature = f"{name}({_canonical(params)})"
            selector = "0x" + keccak(text=signature)[:4].hex()
            found.setdefault(selector, [])
            if signature not in found[selector]:
                found[selector].append(signature)
    return found


def describe(selector: str) -> str:
    selector = selector.lower()
    if not selector.startswith("0x"):
        selector = "0x" + selector
    selector = selector[:10]
    if selector in _BUILTIN:
        return _BUILTIN[selector]
    matches = error_selectors().get(selector)
    if not matches:
        return "UNKNOWN — not declared in any installed 1inch source"
    return " | ".join(matches)


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        for selector in argv[1:]:
            print(f"{selector}  {describe(selector)}")
        return 0

    table = error_selectors()
    print(f"{len(table)} distinct error selectors across {SOLIDITY}\n")
    for selector in sorted(table):
        print(f"{selector}  {' | '.join(table[selector])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
