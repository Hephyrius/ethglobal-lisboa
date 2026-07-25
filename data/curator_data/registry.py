"""The registry: resolve mandate source keys, fan out, merge.

This is the extension point the whole lane exists to provide. It knows about
`DataSource` and nothing else — no provider name appears in this file, and
none ever should. Adding Chainlink means writing one source module and adding
one line to `sources/__init__.py`; this file does not change.

Two behaviours are load-bearing and both are about *not* crashing:

  * **Unknown key → error, not exception.** A mandate is user-authored data. It
    can name a source that was never registered, or one removed since genesis.
    That degrades the snapshot; it does not stop the agent.
  * **Failing source → error, not exception.** The decision loop must survive a
    rate-limited gateway. The model is shown `snapshot.errors[]` so it can
    reason about what it could not see, rather than silently treating a
    partial view as complete.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping

from curator_schema.models import Fact, MarketSnapshot, SourceError

from .config import Settings
from .facts import dedupe_ids, utcnow
from .ports import DataSource

logger = logging.getLogger(__name__)

#: A source is registered as a factory, not an instance. Sources open HTTP
#: clients and read credentials, so constructing every registered source just
#: to answer a mandate that names one of them would be wasteful and would fail
#: loudly for sources whose credentials are absent but unneeded.
SourceFactory = Callable[[Settings], DataSource]


class Registry:
    """Implements the frozen `DataSourceRegistry` port.

    Sources are instantiated lazily on first use and cached for the registry's
    lifetime, so a long-lived agent reuses connection pools across ticks.
    """

    def __init__(
        self,
        factories: Mapping[str, SourceFactory],
        settings: Settings | None = None,
    ):
        self._factories = dict(factories)
        self._settings = settings or Settings()
        self._instances: dict[str, DataSource] = {}

    # ── introspection ─────────────────────────────────────────────────────

    def available(self) -> list[str]:
        """Registered keys. The genesis UI offers these as the grantable set."""
        return sorted(self._factories)

    def describe(self) -> list[dict[str, str]]:
        """Key + human description for every source, for pickers and docs.

        Instantiates each source, so it needs whatever credentials they read;
        a source that cannot be constructed is reported rather than raised.
        """
        out = []
        for key in self.available():
            try:
                source = self._resolve(key)
                describe = getattr(source, "describe", None)
                out.append(
                    describe() if callable(describe) else {"key": key, "description": ""}
                )
            except Exception as exc:  # noqa: BLE001 - reporting, not handling
                out.append({"key": key, "description": f"unavailable: {exc}"})
        return out

    def register(self, key: str, factory: SourceFactory) -> None:
        """Add a source at runtime.

        The supported path for a third party — including our own MCP server's
        tests — to extend the registry without editing this package.
        """
        if not key:
            raise ValueError("a source key is required")
        self._factories[key] = factory
        self._instances.pop(key, None)

    # ── the main event ────────────────────────────────────────────────────

    async def snapshot(self, source_keys: list[str], assets: list[str]) -> MarketSnapshot:
        """Fan out to the named sources concurrently and merge their facts.

        `source_keys` comes from `Mandate.permitted_data_sources` and is the
        access-control boundary: a registered source not named here is never
        consulted.
        """
        taken_at = utcnow()
        requested = list(dict.fromkeys(source_keys))  # de-dup, preserve order
        errors: list[SourceError] = []

        known: list[str] = []
        for key in requested:
            if key in self._factories:
                known.append(key)
            else:
                errors.append(
                    SourceError(
                        source=key,
                        message=(
                            f"unknown data source '{key}' — not registered. "
                            f"Available: {', '.join(self.available()) or 'none'}"
                        ),
                    )
                )

        results = await asyncio.gather(
            *(self._fetch_one(key, assets) for key in known),
            return_exceptions=False,
        )

        facts: list[Fact] = []
        for key, (source_facts, source_error, notes) in zip(known, results):
            if source_error is not None:
                errors.append(source_error)
            errors.extend(SourceError(source=key, message=note) for note in notes)
            facts.extend(self._enforce_provenance(key, source_facts, errors))

        return MarketSnapshot(
            taken_at=taken_at,
            facts=dedupe_ids(sorted(facts, key=lambda f: f.id)),
            errors=errors,
        )

    async def _fetch_one(
        self, key: str, assets: list[str]
    ) -> tuple[list[Fact], SourceError | None, list[str]]:
        """Call one source. Never raises — that is the entire contract here."""
        try:
            source = self._resolve(key)
        except Exception as exc:  # noqa: BLE001 - construction failure is a source failure
            logger.warning("data source %s failed to construct: %s", key, exc)
            return [], SourceError(source=key, message=f"could not initialise: {exc}"), []

        facts: list[Fact] = []
        error: SourceError | None = None
        try:
            result = await asyncio.wait_for(
                source.fetch(list(assets)), timeout=self._settings.source_timeout_s
            )
            facts = list(result or [])
        except asyncio.TimeoutError:
            logger.warning("data source %s timed out", key)
            error = SourceError(
                source=key,
                message=f"timed out after {self._settings.source_timeout_s:g}s",
            )
        except asyncio.CancelledError:
            # Cooperative cancellation belongs to the caller, not to us.
            raise
        except Exception as exc:  # noqa: BLE001 - a source must not kill the loop
            # The message is already carried into errors[] and shown to the
            # model; a stack trace at WARNING would bury the demo's own output.
            logger.warning("data source %s failed: %s", key, exc)
            logger.debug("data source %s traceback", key, exc_info=True)
            error = SourceError(source=key, message=f"{type(exc).__name__}: {exc}")

        # Drained even on failure: a source that fetched three protocols and
        # then blew up on the fourth should still report the three notes.
        return facts, error, self._drain_notes(key, source)

    @staticmethod
    def _drain_notes(key: str, source: DataSource) -> list[str]:
        """Collect a source's partial-failure notes, if it records any.

        Optional by design — `drain_notes` is not part of the frozen port, so a
        source without it is still a valid source.
        """
        drain = getattr(source, "drain_notes", None)
        if not callable(drain):
            return []
        try:
            return [str(note) for note in (drain() or [])]
        except Exception as exc:  # noqa: BLE001 - reporting must not break reporting
            logger.warning("draining notes from %s failed: %s", key, exc)
            return []

    @staticmethod
    def _enforce_provenance(
        key: str, facts: Iterable[Fact], errors: list[SourceError]
    ) -> list[Fact]:
        """Guarantee `Fact.source` is the registry key that produced it.

        A source mislabelling its own facts is a bug in this lane, but it would
        surface as the dApp attributing a number to the wrong provider — a
        credibility problem in front of judges. Correct it, and record that the
        correction happened so the bug is visible rather than absorbed.
        """
        corrected: list[Fact] = []
        mislabelled = 0
        for fact in facts:
            if fact.source != key:
                mislabelled += 1
                fact = fact.model_copy(update={"source": key})
            corrected.append(fact)
        if mislabelled:
            errors.append(
                SourceError(
                    source=key,
                    message=(
                        f"{mislabelled} fact(s) carried the wrong provenance and were "
                        f"re-attributed to '{key}' — source bug, facts retained"
                    ),
                )
            )
        return corrected

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _resolve(self, key: str) -> DataSource:
        source = self._instances.get(key)
        if source is None:
            source = self._factories[key](self._settings)
            self._instances[key] = source
        return source

    async def aclose(self) -> None:
        """Close every instantiated source. Safe to call repeatedly."""
        for key, source in list(self._instances.items()):
            close = getattr(source, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - teardown must not raise
                logger.warning("closing source %s failed: %s", key, exc)
        self._instances.clear()

    async def __aenter__(self) -> Registry:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


def build_registry(
    settings: Settings | None = None,
    factories: Mapping[str, SourceFactory] | None = None,
) -> Registry:
    """Registry over the built-in sources.

    `factories` overrides the built-in table wholesale — used by tests and by
    anyone embedding the registry with their own source set.
    """
    from .sources import SOURCE_FACTORIES

    return Registry(
        factories=SOURCE_FACTORIES if factories is None else factories,
        settings=settings or Settings.from_env(),
    )


__all__ = ["Registry", "SourceFactory", "build_registry"]
