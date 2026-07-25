"""A loop-safe cache for `httpx.AsyncClient`.

Deliberately a copy of `data/curator_data/http.py`, not an import of it. The two
packages are separately publishable and have no dependency on each other —
`curator-data` ships to PyPI on its own — and forty lines of duplication costs
much less than a dependency edge whose only purpose is to avoid them. If you
change one, change both.

## The bug

`get_venue()` caches adapters in a module-level `_CACHE` so one connection pool
is reused across ticks, and each adapter lazily builds one `httpx.AsyncClient`.
An `AsyncClient` binds its transport to the event loop that first used it, and a
module-level cache outlives any one loop — so anything running `asyncio.run`
more than once in a process (the CLI, the test suite, some worker
configurations) eventually asks a closed loop to do work and gets
`RuntimeError: Event loop is closed`.

It surfaced first in `curator_data`, twice, on ticks hours apart: a source that
worked all day and then failed once. There is nothing in this package that makes
it immune, so it is fixed here before it costs a demo.

## The fix

Remember which loop built the client; rebuild if the running loop differs. The
stale client is **discarded, not closed** — `aclose()` would have to run on the
loop that is gone, so awaiting it either raises the error we are avoiding or
blocks. Its sockets died with the loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import httpx

__all__ = ["LoopBoundClient"]

logger = logging.getLogger(__name__)


class LoopBoundClient:
    """One `httpx.AsyncClient`, rebuilt whenever the event loop changes."""

    def __init__(self, factory: Callable[[], httpx.AsyncClient]) -> None:
        self._factory = factory
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def get_client(self) -> httpx.AsyncClient:
        """The client for the running loop, building or rebuilding as needed."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Legal to construct outside a loop; it binds on first use.
            loop = None

        if self._client is not None and loop is not None and self._loop is not loop:
            logger.debug("event loop changed under a cached httpx client; rebuilding")
            self._client = None  # deliberately not awaited — see the docstring

        if self._client is None:
            self._client = self._factory()
            self._loop = loop
        return self._client

    def adopt(self, client: httpx.AsyncClient | None) -> None:
        """Use a caller-supplied client and never rebuild it.

        Tests inject a `MockTransport` client. Swapping it out because the loop
        changed would silently un-mock the adapter and start making real
        requests, which is far worse than the error this class prevents.
        """
        if client is None:
            return
        self._client = client
        self._loop = None
        self._factory = lambda: client

    @property
    def live(self) -> httpx.AsyncClient | None:
        """The current client without building one. For teardown checks."""
        return self._client

    async def aclose(self) -> None:
        """Close the client if the loop still exists; drop it either way."""
        client, self._client, self._loop = self._client, None, None
        if client is None:
            return
        try:
            await client.aclose()
        except RuntimeError as exc:  # loop already gone — nothing left to release
            logger.debug("discarding an httpx client bound to a dead loop: %s", exc)
