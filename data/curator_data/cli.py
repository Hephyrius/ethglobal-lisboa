"""`curator-data` — one parameterised tool, not a folder of one-off scripts.

Four subcommands covering everything this lane needs operationally:

    curator-data sources              what can be granted in a mandate
    curator-data protocols            what is configured, and where to add more
    curator-data snapshot             take a real snapshot and print it
    curator-data verify-live          prove the demo path hits live data

`snapshot --json` emits a schema-valid `MarketSnapshot`, so it doubles as a way
to hand another lane real data without them running any of this code.

Output is ASCII: this runs in PowerShell, WSL and macOS terminals, and a
cp1252 console turns box-drawing characters into noise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .config import Settings
from .queries import MARKET_KINDS, errors_as_dicts, pivot_markets, pivot_pools, prices
from .registry import build_registry
from .sources.protocols import ALL
from .verify import report, summarise, verify_live


def _fmt_usd(value: float | None) -> str:
    if value is None:
        return "-"
    for threshold, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= threshold:
            return f"${value / threshold:,.1f}{suffix}"
    return f"${value:,.2f}"


def _fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


# ── subcommands ───────────────────────────────────────────────────────────


def cmd_sources(args: argparse.Namespace) -> int:
    """What a mandate may name in `permitted_data_sources`."""
    registry = build_registry(Settings.from_env())
    described = registry.describe()
    if args.json:
        print(json.dumps(described, indent=2))
        return 0

    print("Registered data sources (name these in Mandate.permitted_data_sources):\n")
    for entry in described:
        print(f"  {entry['key']}")
        print(f"      {entry.get('description', '')}")
        if entry.get("provides"):
            print(f"      provides: {entry['provides']}")
    print("\nAdd one: implement BaseSource in curator_data/sources/, then add a single")
    print("line to SOURCE_FACTORIES in curator_data/sources/__init__.py.")
    return 0


def cmd_protocols(args: argparse.Namespace) -> int:
    """The protocol table — the "adding a protocol is one line" claim, printed."""
    if args.json:
        print(json.dumps([p.__dict__ for p in ALL], indent=2))
        return 0

    print("Configured protocols:\n")
    print(f"  {'key':<14} {'family':<10} {'chain':<7} {'on':<4} label")
    print(f"  {'-' * 14} {'-' * 10} {'-' * 7} {'-' * 4} {'-' * 24}")
    for p in ALL:
        print(
            f"  {p.key:<14} {p.family:<10} {p.chain:<7} "
            f"{'yes' if p.enabled else 'no':<4} {p.label}"
        )
    print("\nAdding a protocol is one Protocol(...) line in")
    print("curator_data/sources/protocols.py - Messari's standardized schema means")
    print("every lending market answers the same query, so no adapter is needed.")
    return 0


async def _snapshot(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]
    registry = build_registry(settings)
    try:
        if args.sources:
            keys = [s.strip() for s in args.sources.split(",") if s.strip()]
        else:
            keys = registry.sources_providing(*MARKET_KINDS, "price")
        snapshot = await registry.snapshot(keys, assets)
    finally:
        await registry.aclose()

    if args.json:
        # Schema-valid MarketSnapshot: pipe it straight into another lane.
        print(snapshot.model_dump_json(indent=2))
        return 0 if snapshot.facts else 1

    print(f"Snapshot at {snapshot.taken_at.isoformat(timespec='seconds')}")
    print(f"Sources: {', '.join(keys) or 'none'}   Assets: {', '.join(assets)}\n")

    markets = pivot_markets(snapshot)
    if markets:
        print(f"  {'protocol':<14} {'market':<8} {'APY':>8} {'TVL':>10} {'util':>7}")
        print(f"  {'-' * 14} {'-' * 8} {'-' * 8} {'-' * 10} {'-' * 7}")
        for row in markets:
            print(
                f"  {row.protocol:<14} {row.market:<8} {_fmt_pct(row.supply_apy):>8} "
                f"{_fmt_usd(row.tvl_usd):>10} {_fmt_pct(row.utilization):>7}"
            )
        print()

    pools = pivot_pools(snapshot)
    for pool in pools:
        print(f"  pool {pool.protocol} {'/'.join(pool.pair)}: {_fmt_usd(pool.liquidity_usd)}")
    if pools:
        print()

    for symbol, price in prices(snapshot).items():
        via = ", ".join(price["sources"])
        line = f"  price {symbol}: ${price['price_usd']:,.2f}  (via {via}"
        if len(price["sources"]) > 1:
            # Independent mechanisms agreeing is worth showing, not just
            # asserting — and disagreeing is worth showing even more.
            line += f", spread {price['spread_pct']:.2f}%"
            if price["disagreement"]:
                line += " DISAGREEMENT"
        print(line + ")")

    errors = errors_as_dicts(snapshot)
    if errors:
        # Printed last and labelled plainly: a partial snapshot must look
        # partial, or the number above it gets read as the whole market.
        print("\n  Degraded - these sources could not be read:")
        for error in errors:
            print(f"    [{error['source']}] {error['message']}")

    print(f"\n{len(snapshot.facts)} facts, {len(errors)} errors")
    return 0 if snapshot.facts else 1


async def _verify(args: argparse.Namespace) -> int:
    results = await verify_live(Settings.from_env(), only=args.protocol)
    print(report(results))
    _, failed, skipped = summarise(results)
    # Skipped counts as failure here: this command exists to prove the live
    # path works, and "we did not check" is not proof.
    return 1 if (failed or skipped) else 0


# ── entry point ───────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="curator-data",
        description="Market data registry: inspect sources, take snapshots, verify live data.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging to stderr")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_sources = subparsers.add_parser("sources", help="list registered data sources")
    p_sources.add_argument("--json", action="store_true")
    p_sources.set_defaults(func=lambda a: cmd_sources(a))

    p_protocols = subparsers.add_parser("protocols", help="list configured protocols")
    p_protocols.add_argument("--json", action="store_true")
    p_protocols.set_defaults(func=lambda a: cmd_protocols(a))

    p_snapshot = subparsers.add_parser("snapshot", help="take a live MarketSnapshot")
    p_snapshot.add_argument("--assets", default="USDC,WETH", help="comma-separated symbols")
    p_snapshot.add_argument("--sources", default="", help="comma-separated keys (default: all)")
    p_snapshot.add_argument(
        "--json", action="store_true", help="emit a schema-valid MarketSnapshot"
    )
    p_snapshot.set_defaults(func=lambda a: asyncio.run(_snapshot(a)))

    p_verify = subparsers.add_parser(
        "verify-live", help="prove the demo path reaches live gateway data"
    )
    p_verify.add_argument("--protocol", default=None, help="check only this protocol key")
    p_verify.set_defaults(func=lambda a: asyncio.run(_verify(a)))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
