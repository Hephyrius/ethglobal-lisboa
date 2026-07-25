"""Live-path verification.

The Graph disqualifies mocked data, so "does this actually hit the live
gateway" is a submission gate rather than a nicety. The unit tests deliberately
never touch the network; this module is the counterpart that only touches the
network, and it is the single command that proves the demo path.

It is also the macOS handoff check: a teammate who clones the repo at 10:00
runs `curator-data verify-live` and learns, in one screen, whether their
environment can reach real data and which protocol is at fault if not.

Importable rather than buried in the CLI so tests and other tooling can call it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .config import Settings
from .facts import utcnow
from .sources.aave import AaveSource
from .sources.chainlink import ChainlinkSource
from .sources.messari import MessariSource
from .sources.protocols import ALL, Protocol
from .sources.token_api import TokenApiSource


@dataclass
class CheckResult:
    """One verification step. `ok` is what the exit code is built from."""

    name: str
    ok: bool
    detail: str
    #: Non-fatal: a skipped check is reported but does not fail the run.
    skipped: bool = False
    sample: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIP"
        return "PASS" if self.ok else "FAIL"


def check_credentials(settings: Settings) -> list[CheckResult]:
    """Credentials first: every downstream failure is otherwise ambiguous."""
    results = [
        CheckResult(
            name="GRAPH_API_KEY",
            ok=settings.has_gateway_credential,
            detail=(
                "present"
                if settings.has_gateway_credential
                else "MISSING - get one free at https://thegraph.com/studio -> API Keys, "
                "then put GRAPH_API_KEY=... in .env"
            ),
        ),
        CheckResult(
            name="TOKEN_API_KEY",
            ok=settings.has_token_api_credential,
            detail=(
                "present (falls back to GRAPH_API_KEY)"
                if settings.has_token_api_credential
                else "MISSING - prices will be unavailable"
            ),
        ),
    ]
    return results


async def check_protocol(protocol: Protocol, settings: Settings) -> CheckResult:
    """Query one subgraph for real and report what came back.

    Drives `MessariSource` rather than issuing its own GraphQL, so this
    verifies the code path the demo actually runs — including the DEX
    schema-family fallback. A check that passes while the source would fail
    (or vice versa) is worse than no check.

    No asset filter: the question here is "did this subgraph answer", not
    "does it list USDC".
    """
    name = f"{protocol.key} ({protocol.family})"
    # Dispatch on family: Aave's schema is served by its own source, and
    # running it through the Messari adapter produces a confusing schema error
    # about a query we would never actually send it.
    source = (
        AaveSource(settings, protocols=[protocol])
        if protocol.family == "lending-aave"
        else MessariSource(settings, protocols=[protocol])
    )
    try:
        facts = await source.fetch([])
        notes = source.drain_notes()
        if not facts:
            detail = notes[0] if notes else "connected, but produced no facts"
            return CheckResult(name=name, ok=False, detail=detail)

        kinds = sorted({f.kind for f in facts})
        sample = []
        for fact in facts[:3]:
            subject = fact.subject.market or fact.subject.token or "/".join(
                fact.subject.pair or []
            )
            value = (
                f"{fact.value * 100:.2f}%"
                if fact.unit == "apy_fraction"
                else f"${fact.value:,.0f}"
                if fact.unit == "usd"
                else f"{fact.value:.2f}"
            )
            sample.append(f"{subject} {fact.kind}: {value}")

        return CheckResult(
            name=name,
            ok=True,
            detail=f"{len(facts)} facts ({', '.join(kinds)})"
            + (f" - note: {notes[0]}" if notes else ""),
            sample=sample,
        )
    except Exception as exc:  # noqa: BLE001 - report every failure mode
        return CheckResult(name=name, ok=False, detail=f"{type(exc).__name__}: {exc}")
    finally:
        await source.close()


async def check_chainlink(
    settings: Settings, symbols: tuple[str, ...] = ("WETH", "USDC")
) -> CheckResult:
    """Read the on-chain feeds. Needs an RPC, not a credential."""
    source = ChainlinkSource(settings)
    try:
        facts = await source.fetch(list(symbols))
        notes = source.drain_notes()
        if not facts:
            return CheckResult(
                name="chainlink",
                ok=False,
                detail=notes[0] if notes else "no feeds returned a price",
            )
        return CheckResult(
            name="chainlink",
            ok=True,
            detail=f"{len(facts)} feed(s) read from {settings.rpc_url}",
            sample=[f"{f.subject.token} = ${f.value:,.4f}" for f in facts],
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name="chainlink", ok=False, detail=f"{type(exc).__name__}: {exc}")
    finally:
        await source.close()


async def check_source(key: str, settings: Settings, assets: tuple[str, ...]) -> CheckResult:
    """Drive any registered source through the registry and report what came back.

    Generic on purpose. Wave 1 and Wave 2 added six sources and none of them
    reached this gate, so `verify-live` was reporting 6/7 green while checking
    four of ten sources. A gate that only knows about the sources that existed
    when it was written is not a gate.
    """
    from .registry import build_registry

    registry = build_registry(settings)
    try:
        snapshot = await registry.snapshot([key], list(assets))
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name=key, ok=False, detail=f"{type(exc).__name__}: {exc}")
    finally:
        await registry.aclose()

    if snapshot.errors:
        return CheckResult(name=key, ok=False, detail=snapshot.errors[0].message[:150])
    if not snapshot.facts:
        note = snapshot.notes[0].message if snapshot.notes else "no facts and no explanation"
        return CheckResult(name=key, ok=False, detail=note[:150])

    kinds = sorted({f.kind for f in snapshot.facts})
    sample = []
    for fact in snapshot.facts[:2]:
        subject = fact.subject.market or fact.subject.token or fact.subject.protocol or "-"
        value = (
            f"{fact.value:.2%}"
            if fact.unit in ("apy_fraction", "ratio")
            else f"${fact.value:,.2f}"
            if fact.unit == "usd"
            else f"{fact.value:g}"
        )
        sample.append(f"{subject} {fact.kind}: {value}")
    return CheckResult(
        name=key,
        ok=True,
        detail=f"{len(snapshot.facts)} facts ({', '.join(kinds)})",
        sample=sample,
    )


async def check_token_api(settings: Settings, symbol: str = "WETH") -> CheckResult:
    source = TokenApiSource(settings)
    try:
        facts = await source.fetch([symbol])
        if facts:
            return CheckResult(
                name="token_api",
                ok=True,
                detail=f"{symbol} = ${facts[0].value:,.2f}",
            )
        notes = source.drain_notes()
        return CheckResult(
            name="token_api",
            ok=False,
            detail=notes[0] if notes else "no price returned",
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name="token_api", ok=False, detail=f"{type(exc).__name__}: {exc}")
    finally:
        await source.close()


async def verify_live(
    settings: Settings | None = None,
    *,
    only: str | None = None,
    include_token_api: bool = True,
) -> list[CheckResult]:
    """Run the full live check. Returns every result; the caller decides on exit.

    Protocols are checked concurrently — with five or more configured, serial
    checking makes a routine verification feel broken.
    """
    resolved = settings or Settings.from_env()
    results = check_credentials(resolved)

    protocols = [p for p in ALL if p.enabled and (only is None or p.key == only)]
    if only and not protocols:
        results.append(
            CheckResult(name=only, ok=False, detail=f"no protocol named '{only}' is configured")
        )
        return results

    if not resolved.has_gateway_credential:
        # Without a credential every protocol check would fail identically and
        # bury the one line that actually matters.
        results += [
            CheckResult(
                name=f"{p.key} ({p.family})",
                ok=False,
                skipped=True,
                detail="skipped - no GRAPH_API_KEY",
            )
            for p in protocols
        ]
    else:
        results += list(
            await asyncio.gather(*(check_protocol(p, resolved) for p in protocols))
        )

    if only is None:
        # Needs no credential, so it is checked whatever else is missing — and
        # it is the reason price facts survive an absent API key.
        if resolved.rpc_url:
            results.append(await check_chainlink(resolved))
        else:
            results.append(
                CheckResult(
                    name="chainlink",
                    ok=False,
                    skipped=True,
                    detail="skipped - no DATA_RPC_URL / ANVIL_RPC_URL / BASE_RPC_URL",
                )
            )

    if only is None:
        # Every other registered source, through the generic check. Named
        # explicitly rather than "everything else" so adding a source shows up
        # here automatically but the bespoke checks above are not duplicated.
        from .sources import PROTOCOL_BACKED, SOURCE_FACTORIES

        # `PROTOCOL_BACKED` comes from sources/ rather than being restated
        # here: a second list of source keys is one that goes stale, which is
        # what `test_source_agnostic` exists to prevent.
        covered = set(PROTOCOL_BACKED) | {"chainlink", "token_api"}
        for key in sorted(set(SOURCE_FACTORIES) - covered):
            results.append(await check_source(key, resolved, ("USDC", "WETH", "wstETH")))

    if include_token_api and only is None:
        if resolved.has_token_api_credential:
            results.append(await check_token_api(resolved))
        else:
            results.append(
                CheckResult(
                    name="token_api",
                    ok=False,
                    skipped=True,
                    detail="skipped - no TOKEN_API_KEY or GRAPH_API_KEY",
                )
            )

    return results


def summarise(results: list[CheckResult]) -> tuple[int, int, int]:
    """(passed, failed, skipped). Skipped never counts as failure."""
    passed = sum(1 for r in results if r.ok and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = len(results) - passed - skipped
    return passed, failed, skipped


def report(results: list[CheckResult]) -> str:
    """Human-readable summary. ASCII only - Windows consoles are cp1252."""
    lines = [f"Live data verification - {utcnow().isoformat(timespec='seconds')}", ""]
    for result in results:
        lines.append(f"  [{result.status}] {result.name}: {result.detail}")
        lines += [f"           {s}" for s in result.sample]

    passed, failed, skipped = summarise(results)
    lines += ["", f"{passed} passed, {failed} failed, {skipped} skipped"]
    if failed or skipped:
        lines.append(
            "Live gateway data is a submission gate (The Graph disqualifies mocked "
            "data) - resolve the above before the demo."
        )
    return "\n".join(lines)


__all__ = ["CheckResult", "verify_live", "check_protocol", "check_token_api", "report", "summarise"]
