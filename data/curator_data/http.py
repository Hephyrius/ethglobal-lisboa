"""A loop-safe cache for `httpx.AsyncClient`.

## The bug this exists to kill

Two journalled ticks failed with `RuntimeError: Event loop is closed`, one on
`token_api` and one on `aave`. Nothing in either source is wrong. The cause is
the interaction of two entirely reasonable decisions made in different files:

  * `Registry` caches source *instances* for its lifetime, so a long-lived agent
    reuses connection pools across ticks (`registry.py`).
  * Each source lazily constructs one `httpx.AsyncClient` and holds it.

An `AsyncClient` binds its transport to the event loop that was running when its
connection pool was first used. `curator_data.default:registry` is a module-level
singleton, so it outlives any individual loop — and a client built under a loop
that has since closed raises on its next request. It surfaces as a source that
worked for hours and then failed once, which is about the least diagnosable
shape a bug can have.

Anything that runs `asyncio.run()` more than once in a process hits this: the
CLI, the MCP server, the test suite, and FastAPI under some worker
configurations. It is not exotic.

## The fix

Remember which loop built the client. On every access, compare against the
running loop; if it changed, drop the old client and build a new one.

The stale client is **discarded, not closed**. `aclose()` would have to run on
the loop that created it, and that loop is gone — awaiting it either raises the
same error we are avoiding or blocks. Its sockets died with its loop, so there
is nothing left to release; holding a reference to it just to be tidy would leak
one dead object per loop.

This is duplicated as `venues/http.py` rather than shared. `curator_data` and
`venues` are separately publishable packages with no dependency on each other,
and 40 lines is a much smaller cost than a dependency edge that exists only to
avoid them.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import httpx

__all__ = ["LoopBoundClient"]

logger = logging.getLogger(__name__)


class LoopBoundClient:
    """One `httpx.AsyncClient`, rebuilt whenever the event loop changes.

    Usage mirrors the lazy property it replaces::

        self._http = LoopBoundClient(lambda: httpx.AsyncClient(timeout=30.0))
        ...
        response = await self._http.get_client().get(url)
    """

    def __init__(self, factory: Callable[[], httpx.AsyncClient]) -> None:
        self._factory = factory
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def get_client(self) -> httpx.AsyncClient:
        """The client for the running loop, building or rebuilding as needed."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Constructing a client outside a loop is legal; it binds on first
            # use. Only rebind once there is a loop to compare against.
            loop = None

        if self._client is not None and loop is not None and self._loop is not loop:
            logger.debug(
                "event loop changed under a cached httpx client; rebuilding "
                "(old loop closed=%s)",
                getattr(self._loop, "is_closed", lambda: "?")(),
            )
            # Deliberately not awaited — see the module docstring.
            self._client = None

        if self._client is None:
            self._client = self._factory()
            self._loop = loop

        return self._client

    def adopt(self, client: httpx.AsyncClient | None) -> None:
        """Use a caller-supplied client and never rebuild it.

        Tests inject a client backed by `MockTransport`; silently replacing it
        because the loop changed would make the mock stop being used, which is
        far worse than the error this class prevents.
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
        """Close the client if it belongs to the running loop; drop it either way."""
        client, self._client, self._loop = self._client, None, None
        if client is None:
            return
        try:
            await client.aclose()
        except RuntimeError as exc:  # loop already gone — nothing left to release
            logger.debug("discarding an httpx client bound to a dead loop: %s", exc)
