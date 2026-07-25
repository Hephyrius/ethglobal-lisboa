"""The `AsyncWeb3` this lane builds, and the one round trip web3 repeats forever.

Found while measuring request #46. A single `GET /vault/{addr}/state` issued
**28** JSON-RPC requests, and 18 of them were `eth_chainId` — one per underlying
call, none of them ours. `web3/middleware/validation.py` does
`w3_chain_id = await async_w3.eth.chain_id` inside its per-request path, so every
`eth_call` silently pays for a second round trip. On a fork answering in 0.22s
that is ~4s of the 4.70s measured, and it is invisible from the application side:
nothing in this repo asks for the chain id at all.

The obvious fix is to drop `ValidationMiddleware`, and it is the wrong one. What
it validates is that a transaction's declared `chainId` matches the node's — for
a component whose whole trust model is *"the agent holds a key and executes
directly"*, a guard against signing against the wrong chain is worth keeping.
So the guard stays and the answer gets cached instead: a chain id cannot change
for the life of a connection, which is what makes this safe rather than merely
faster.

web3 7.16 ships no cache middleware of its own — `SimpleCache` does not exist in
this version — so it is ten lines here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from web3 import AsyncWeb3
from web3.middleware import Web3Middleware

if TYPE_CHECKING:  # pragma: no cover - typing only
    from web3.providers.async_base import AsyncBaseProvider
    from web3.types import RPCEndpoint, RPCResponse

__all__ = ["CachedChainId", "make_async_web3"]

log = logging.getLogger(__name__)

_CHAIN_ID = "eth_chainId"


class CachedChainId(Web3Middleware):
    """Answer `eth_chainId` from memory after the first successful reply.

    **Errors are never cached.** A node that is briefly unreachable would
    otherwise pin the connection to a failure it has already recovered from —
    the same trap as caching a failed `symbol()` lookup, and worse here, because
    a stuck chain id feeds the guard that decides whether a signed transaction is
    going to the right chain.

    **The lock is not incidental.** A cache alone took one state read from 28
    round trips to 17, not to 11: the eight vault reads now go out together, so
    all eight miss an empty cache and all eight ask. Coalescing is what turns
    "cached after the first read" into "asked once, ever" — and it is the shape
    of the fix rather than a warm-up call because it also covers a reconnect,
    where the herd re-forms.
    """

    def __init__(self, w3: Any) -> None:
        super().__init__(w3)
        self._cached: RPCResponse | None = None
        self._lock = asyncio.Lock()

    async def async_wrap_make_request(self, make_request):  # type: ignore[override]
        async def middleware(method: RPCEndpoint, params: Any) -> RPCResponse:
            if method != _CHAIN_ID:
                return await make_request(method, params)
            if self._cached is None:
                async with self._lock:
                    # Re-checked inside the lock: whoever was ahead in the queue
                    # has already answered the question by the time we get here.
                    if self._cached is None:
                        response = await make_request(method, params)
                        if "result" not in response:
                            return response
                        self._cached = response
                        log.debug("chain id %s cached for this connection", response["result"])
            # A copy: middleware downstream is free to mutate what it is handed,
            # and the cached dict has to outlive every one of them.
            return dict(self._cached)  # type: ignore[return-value]

        return middleware


def make_async_web3(provider: AsyncBaseProvider) -> AsyncWeb3:
    """The only place this lane constructs an `AsyncWeb3`.

    A function rather than an inline call so the tests measuring round trips
    build their client exactly the way production does — a count taken against a
    differently-assembled web3 would be measuring the wrong object.
    """
    w3 = AsyncWeb3(provider)
    w3.middleware_onion.add(CachedChainId, name="cached_chain_id")
    return w3
