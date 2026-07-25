"""Read SwapVM strategy bytes out of the Solidity builder.

The encoding lives in `solidity/src/SwapVMProgramBuilder.sol`, compiled against
1inch's own `ProgramBuilder`/`MakerTraitsLib`. This module only calls it and
decodes the result — deliberately, so there is exactly one implementation of
1inch's bytecode format and it is theirs.

Two ways to reach the builder, tried in this order:

1. **Ephemeral `eth_call` with a state override** (default). The builder is a
   pure function, so it is injected at a throwaway address for the duration of
   one call. Nothing to deploy, nothing to fund, works on a fresh fork.
2. **A deployed instance**, when `AQUA_PROGRAM_BUILDER_ADDRESS` is set or the
   endpoint refuses state overrides.

The compiled artifact is committed at `venues/aqua/program_builder.json`, so
this works with no Foundry toolchain present.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from eth_abi import decode as abi_decode

from ..abi import encode_call
from ..errors import VenueError
from ..rpc import RpcClient, StateOverrideUnsupportedError

ARTIFACT_PATH: Final[Path] = Path(__file__).parent / "program_builder.json"

#: Canonical signature of the entry point. Sorting happens on-chain so Python
#: never has to know that WETH sorts below USDC.
BUILD_STRATEGY_SORTED: Final[str] = (
    "buildStrategySorted(address,address,address,uint32,uint256)"
)
BUILD_XYC_PROGRAM: Final[str] = "buildXYCProgram(uint32,uint256)"


class ProgramBuilderUnavailableError(VenueError):
    """The builder could not be reached and no deployed address was configured."""


@lru_cache(maxsize=1)
def load_artifact() -> dict:
    if not ARTIFACT_PATH.exists():
        raise ProgramBuilderUnavailableError(
            f"{ARTIFACT_PATH} is missing. Regenerate it with "
            f"`sh venues/aqua/solidity/build.sh`."
        )
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def runtime_bytecode() -> str:
    code = load_artifact().get("deployedBytecode")
    if not code or code == "0x":
        raise ProgramBuilderUnavailableError(
            "artifact has no deployedBytecode; re-run venues/aqua/solidity/build.sh"
        )
    return code


@dataclass(frozen=True, slots=True)
class Strategy:
    """What `Aqua.ship()` needs, and what identifies the position afterwards.

    `token_a`/`token_b` come back sorted by the contract. The `amounts` passed
    to `ship()` MUST line up with this order — that is the whole reason they are
    returned together rather than left to the caller to re-derive.
    """

    strategy: str  # abi.encode(ISwapVM.Order) — opaque to us, by design
    strategy_hash: str
    token_a: str
    token_b: str


class ProgramBuilder:
    """Client for the Solidity builder contract."""

    def __init__(
        self,
        rpc: RpcClient,
        *,
        address: str | None = None,
    ) -> None:
        self._rpc = rpc
        self._address = address or os.environ.get("AQUA_PROGRAM_BUILDER_ADDRESS") or None
        #: Flips to True after a node rejects state overrides, so we stop
        #: retrying a call we know will fail.
        self._overrides_unsupported = False

    async def _call(self, calldata: str) -> str:
        # A configured deployment is authoritative — no override needed.
        if self._address:
            return await self._rpc.eth_call(self._address, calldata)

        try:
            return await self._rpc.call_ephemeral(runtime_bytecode(), calldata)
        except StateOverrideUnsupportedError as exc:
            self._overrides_unsupported = True
            raise ProgramBuilderUnavailableError(
                "this RPC endpoint does not support eth_call state overrides, and "
                "AQUA_PROGRAM_BUILDER_ADDRESS is not set. Either point BASE_RPC_URL / "
                "ANVIL_RPC_URL at an endpoint that does (anvil and Alchemy both do), "
                "or deploy SwapVMProgramBuilder once and set that variable."
            ) from exc

    async def build_strategy(
        self,
        maker: str,
        token0: str,
        token1: str,
        *,
        fee_bps: int = 0,
        salt: int = 0,
    ) -> Strategy:
        """Compile a constant-product maker position for `maker`.

        `maker` is the vault: tokens stay in it, and only Aqua's virtual
        balances change. Token order does not matter — the contract sorts.
        """
        calldata = encode_call(BUILD_STRATEGY_SORTED, maker, token0, token1, fee_bps, salt)
        raw = await self._call(calldata)

        strategy, strategy_hash, token_a, token_b = abi_decode(
            ["bytes", "bytes32", "address", "address"], bytes.fromhex(raw[2:])
        )
        if not strategy:
            raise ProgramBuilderUnavailableError(
                "builder returned empty strategy bytes — the call reverted or the "
                "artifact is stale"
            )
        return Strategy(
            strategy="0x" + strategy.hex(),
            strategy_hash="0x" + strategy_hash.hex(),
            token_a=_checksum_free(token_a),
            token_b=_checksum_free(token_b),
        )

    async def build_program(self, *, fee_bps: int = 0, salt: int = 0) -> str:
        """Just the program bytecode. Useful for inspection and for the demo —
        showing the actual SwapVM instruction bytes makes the integration
        legible rather than a black box."""
        raw = await self._call(encode_call(BUILD_XYC_PROGRAM, fee_bps, salt))
        (program,) = abi_decode(["bytes"], bytes.fromhex(raw[2:]))
        return "0x" + program.hex()


def _checksum_free(address: str) -> str:
    """eth_abi returns lowercase addresses; the schema accepts any case but
    consistency makes diffs readable."""
    return address if address.startswith("0x") else "0x" + address
