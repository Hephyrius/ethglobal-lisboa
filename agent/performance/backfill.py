"""Reconstructing a vault's share-price curve from chain history.

    uv run python -m agent.performance.backfill                 # every known vault
    uv run python -m agent.performance.backfill 0xVault…        # one vault
    uv run python -m agent.performance.backfill --dry-run

## Why bother, when recording forward is easier

Because a chart that starts the moment we shipped the chart looks like a mock,
and because history is genuinely recoverable here rather than being invented.
Anvil keeps every block it has produced, so `eth_call` at an old block number
returns what the vault *actually* reported then. These points are reconstructed,
not modelled — which is why they are marked `source="backfill"` and are as real
as the live ones.

It also covers the honest gap in the forward recorder: points are appended when
someone reads `/state` or runs a tick, so a vault nobody looked at for two hours
has a hole. This fills it after the fact.

## Which blocks

Not a fixed stride. A vault's worth changes when *something happens to it* — a
deposit, a withdrawal, an agent execution — and between those events the share
price is flat by construction. So the block list comes from `eth_getLogs` on the
vault's own address, which yields exactly the event-spaced series the schema
describes, plus the current head so the curve reaches the present.

Sampling on a stride instead would do far more RPC work and produce a series
whose flat stretches are indistinguishable from missing data.

## Deliberately no allocation breakdown

`holdings()` returns a dynamic array of structs whose ABI decoding is Lane A's
to own, and a wrong decode would put a wrong slice in the allocation chart.
Backfilled points therefore carry `total_assets` and `share_price` but no
`allocation`, which the chart renders as an unknown stretch rather than a
confident wrong one. Live points, which come from a real `VaultState`, have it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime

import httpx
from curator_schema import PerformancePoint

from ..config import settings as load_settings
from ..deployments import deployments_path
from .store import PerformanceStore

__all__ = ["backfill_vault", "main"]

log = logging.getLogger(__name__)

# Function selectors, each computed with `Web3.keccak` and checked against the
# deployed vault on the fork rather than recalled. A wrong selector here would
# not error — `eth_call` to a non-existent function on a contract with no
# fallback returns `0x`, which reads as "the vault did not exist yet" and would
# silently produce an empty history.
_CONVERT_TO_ASSETS = "0x07a2d13a"  # convertToAssets(uint256)
_TOTAL_ASSETS = "0x01e1d114"  # totalAssets()
_TOTAL_SUPPLY = "0x18160ddd"  # totalSupply()
_FACTORY_VAULTS = "0x8220ef5b"  # VaultFactory.vaults()

#: One whole share, in 18-decimal share units. `convertToAssets(1e18)` returns
#: the price in BASE-ASSET decimals (request #27) — for USDC that is ~1_000_000.
_ONE_SHARE = 10**18

#: Cap on reconstructed points per vault. A long-lived fork can hold thousands
#: of blocks and each point costs four RPC round trips; beyond this the curve
#: gains resolution nobody can see. The most RECENT blocks are kept.
_MAX_POINTS = 400


class _Rpc:
    """Minimal JSON-RPC. No web3 dependency — historical `eth_call` is one field."""

    def __init__(self, url: str, client: httpx.AsyncClient) -> None:
        self._url = url
        self._client = client
        self._id = 0

    async def call(self, method: str, params: list) -> object:
        self._id += 1
        response = await self._client.post(
            self._url,
            json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params},
        )
        response.raise_for_status()
        body = response.json()
        if error := body.get("error"):
            raise RuntimeError(f"{method} failed: {error.get('message', error)}")
        return body.get("result")

    async def eth_call(self, to: str, data: str, block: int | str) -> str | None:
        block_tag = block if isinstance(block, str) else hex(block)
        try:
            result = await self.call("eth_call", [{"to": to, "data": data}, block_tag])
        except RuntimeError as exc:
            # A call at a block before the vault existed reverts. That is not an
            # error worth stopping for; it is the boundary of the history.
            log.debug("eth_call %s at %s: %s", data[:10], block, exc)
            return None
        return result if isinstance(result, str) and result != "0x" else None


def _uint(hexstr: str | None) -> int | None:
    if not hexstr or hexstr == "0x":
        return None
    try:
        return int(hexstr, 16)
    except ValueError:
        return None


async def _fork_block(rpc: _Rpc, head: int) -> int:
    """The block the fork was taken at — the floor of local history.

    Load-bearing, and found the hard way. Asking for logs `fromBlock: 0x0` does
    **not** stay local: anvil forwards any range that predates the fork to the
    upstream Base RPC, which answered

        -32614  eth_getLogs is limited to a 10,000 range

    so the whole backfill degraded to a single point. Nothing before the fork
    block can contain a vault that was deployed on the fork, so the query has
    no business reaching mainnet at all.

    `anvil_nodeInfo` is authoritative; the deployment manifest is the fallback
    for a node that does not expose it; and a 10k window below the head is the
    last resort, chosen to sit exactly inside the upstream limit if the request
    does escape.
    """
    try:
        info = await rpc.call("anvil_nodeInfo", [])
        if isinstance(info, dict):
            config = info.get("forkConfig") or {}
            number = config.get("forkBlockNumber")
            if isinstance(number, int) and number > 0:
                return number
            if isinstance(number, str) and (parsed := _uint(number)):
                return parsed
    except (RuntimeError, httpx.HTTPError) as exc:
        log.debug("anvil_nodeInfo unavailable (%s)", exc)

    import json
    from pathlib import Path

    manifest = deployments_path()
    if manifest.is_file():
        try:
            number = json.loads(manifest.read_text(encoding="utf-8")).get("blockNumber")
            if isinstance(number, int) and number > 0:
                return number
        except ValueError:
            pass

    return max(0, head - 10_000)


async def _event_blocks(rpc: _Rpc, vault: str, head: int) -> list[int]:
    """Blocks where this vault emitted anything, plus the head.

    Queried from the fork block forward, in chunks inside the upstream 10,000
    limit. Anvil answers the local range from memory; the chunking is what keeps
    a request from being forwarded and rejected.
    """
    blocks: set[int] = {head}
    floor = await _fork_block(rpc, head)

    logs: list = []
    start = floor
    try:
        while start <= head:
            stop = min(start + 9_999, head)
            chunk = await rpc.call(
                "eth_getLogs",
                [{"address": vault, "fromBlock": hex(start), "toBlock": hex(stop)}],
            )
            logs.extend(chunk or [])
            start = stop + 1
    except (RuntimeError, httpx.HTTPError) as exc:
        log.warning("eth_getLogs failed for %s (%s); backfilling the head only", vault, exc)
        return sorted(blocks)

    for entry in logs or []:
        if number := _uint(entry.get("blockNumber")):
            blocks.add(number)
            # The block before an event is the "just before this happened"
            # reading. Without it a deposit looks instantaneous on the chart
            # rather than as a step from a previous level.
            if number > 1:
                blocks.add(number - 1)

    return sorted(blocks)


async def _block_time(rpc: _Rpc, number: int) -> datetime | None:
    block = await rpc.call("eth_getBlockByNumber", [hex(number), False])
    if not isinstance(block, dict):
        return None
    stamp = _uint(block.get("timestamp"))
    return None if stamp is None else datetime.fromtimestamp(stamp, tz=UTC)


async def _point_at(rpc: _Rpc, vault: str, number: int) -> PerformancePoint | None:
    total_assets = _uint(await rpc.eth_call(vault, _TOTAL_ASSETS, number))
    total_supply = _uint(await rpc.eth_call(vault, _TOTAL_SUPPLY, number))
    if total_assets is None or total_supply is None:
        return None  # the vault did not exist yet at this block

    share_price = None
    if total_supply > 0:
        argument = hex(_ONE_SHARE)[2:].rjust(64, "0")
        share_price = _uint(await rpc.eth_call(vault, _CONVERT_TO_ASSETS + argument, number))

    at = await _block_time(rpc, number)
    if at is None:
        return None

    return PerformancePoint(
        timestamp=at,
        block_number=number,
        share_price=None if share_price is None else str(share_price),
        total_assets=str(total_assets),
        total_supply=str(total_supply),
        source="backfill",
    )


async def backfill_vault(
    vault: str, *, rpc_url: str, store: PerformanceStore, dry_run: bool = False
) -> int:
    """Reconstruct and persist one vault's history. Returns points written."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        rpc = _Rpc(rpc_url, client)

        head = _uint(await rpc.call("eth_blockNumber", []))
        if head is None:
            raise RuntimeError(f"no node at {rpc_url}")

        blocks = await _event_blocks(rpc, vault, head)
        if len(blocks) > _MAX_POINTS:
            log.info(
                "%s has %d candidate blocks; keeping the most recent %d",
                vault,
                len(blocks),
                _MAX_POINTS,
            )
            blocks = blocks[-_MAX_POINTS:]

        points: list[PerformancePoint] = []
        for number in blocks:
            point = await _point_at(rpc, vault, number)
            if point is not None:
                points.append(point)

    log.info("%s: reconstructed %d point(s) from %d block(s)", vault, len(points), len(blocks))
    if dry_run:
        for point in points[:5]:
            log.info(
                "  %s  block %s  price %s",
                point.timestamp,
                point.block_number,
                point.share_price,
            )
        return 0
    return store.extend(vault, points)


async def _factory_vaults(rpc_url: str) -> list[str]:
    """Every vault the factory has ever created, read on-chain.

    The deployment manifest lists only what `Deploy.s.sol` created. Vaults
    minted through the genesis flow — which is most of them once anyone has used
    the dApp — appear nowhere on disk, so a manifest-only backfill silently
    covers the demo vault and none of the interesting ones.

    `vaults()` returns `address[]`: one offset word, one length word, then the
    addresses. Decoded by hand rather than through an ABI codec because that is
    the entire decode and pulling in a dependency for it would be sillier.
    """
    import json
    from pathlib import Path

    factory = None
    manifest = deployments_path()
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            factory = (data.get("contracts") or {}).get("VaultFactory")
        except ValueError:
            factory = None
    if not factory:
        return []

    async with httpx.AsyncClient(timeout=20.0) as client:
        rpc = _Rpc(rpc_url, client)
        raw = await rpc.eth_call(factory, _FACTORY_VAULTS, "latest")

    if not raw:
        return []
    body = bytes.fromhex(raw[2:])
    if len(body) < 64:
        return []
    count = int.from_bytes(body[32:64], "big")
    return [
        "0x" + body[64 + i * 32 + 12 : 64 + (i + 1) * 32].hex()
        for i in range(count)
        if len(body) >= 64 + (i + 1) * 32
    ]


def _known_vaults(store: PerformanceStore, rpc_url: str) -> list[str]:
    """Every vault worth backfilling: factory, manifest, and existing history."""
    import json
    from pathlib import Path

    found: list[str] = list(store.vaults())

    try:
        found.extend(asyncio.run(_factory_vaults(rpc_url)))
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort
        log.warning("could not read the factory's vault list (%s)", exc)

    manifest = deployments_path()
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        found.extend(data.get("vaults") or [])
        if demo := (data.get("demoVault") or {}).get("address"):
            found.append(demo)

    # De-dup case-insensitively; the manifest is checksummed and the store is not.
    seen: dict[str, str] = {}
    for address in found:
        seen.setdefault(address.lower(), address)
    return list(seen.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("vaults", nargs="*", help="vault addresses; default is every known vault")
    parser.add_argument("--rpc-url", default=None, help="defaults to the agent's RPC_URL")
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s"
    )
    # httpx logs one INFO line per request and this makes hundreds; the useful
    # output would be four lines in a thousand.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = load_settings()
    store = PerformanceStore(config.state_dir)
    rpc_url = args.rpc_url or config.rpc_url
    vaults = args.vaults or _known_vaults(store, rpc_url)

    if not vaults:
        log.error("no vaults given and none found in %s", deployments_path())
        return 1

    written = 0
    for vault in vaults:
        try:
            written += asyncio.run(
                backfill_vault(vault, rpc_url=rpc_url, store=store, dry_run=args.dry_run)
            )
        except Exception as exc:  # noqa: BLE001 - one bad vault must not stop the rest
            log.error("%s: %s", vault, exc)

    log.info("wrote %d new point(s)", written)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
