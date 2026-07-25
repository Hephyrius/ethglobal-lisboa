"""A JSON-RPC client that does exactly one thing: `eth_call`.

This lane never sends a transaction — it *builds* them and hands them to the
vault. The only chain access it needs is a read, so this is ~60 lines over the
httpx client already in the tree rather than a node library.

`state_override` is the interesting part. It lets us run a contract that has
never been deployed by injecting its runtime bytecode at an address for the
duration of the call. That removes a deployment step from the critical path:
the SwapVM program builder is a pure function, so there is nothing to persist
and nothing to fund.
"""

from __future__ import annotations

import itertools
from typing import Any, Final

import httpx

from .errors import VenueError
from .http import LoopBoundClient

#: Any address works — the override replaces whatever is (not) there. Reads as
#: "b011de12" so it is recognisable in a trace as the ephemeral builder.
#: Must be valid hex: only 0-9 and a-f. (A "u" here parses as a malformed
#: address and the node rejects the whole call.)
BUILDER_SENTINEL_ADDRESS: Final[str] = "0xb011de12000000000000000000000000000000de"


class RpcError(VenueError):
    """The node refused or failed the call."""

    def __init__(self, method: str, message: str, code: int | None = None) -> None:
        self.method = method
        self.code = code
        super().__init__(f"{method} failed: {message}" + (f" (code {code})" if code else ""))


class StateOverrideUnsupportedError(RpcError):
    """The endpoint does not implement eth_call state overrides.

    Raised distinctly so the caller can fall back to a deployed builder address
    instead of failing the tick. Not every provider supports overrides, and the
    public Base endpoint is the likely offender.
    """


class RpcClient:
    """Minimal async JSON-RPC. Share an httpx client with the rest of the
    harness by passing one in."""

    def __init__(
        self,
        url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._owns_client = client is None
        # Rebuilt if the event loop changes; adapters are cached in a
        # module-level registry that outlives any one loop. See venues/http.py.
        self._bound = LoopBoundClient(lambda: httpx.AsyncClient(timeout=self._timeout))
        self._bound.adopt(client)
        self._ids = itertools.count(1)

    async def __aenter__(self) -> RpcClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._bound.aclose()

    @property
    def _http(self) -> httpx.AsyncClient:
        return self._bound.get_client()

    async def request(self, method: str, params: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
            "params": params,
        }
        try:
            response = await self._http.post(self._url, json=payload)
        except httpx.HTTPError as exc:
            raise RpcError(method, f"transport error: {exc}") from exc

        if response.status_code != 200:
            raise RpcError(method, f"HTTP {response.status_code}: {response.text[:200]}")

        body = response.json()
        if "error" in body:
            error = body["error"]
            message = error.get("message", "unknown error")
            code = error.get("code")
            # Nodes without override support reject the third parameter in
            # assorted ways; all of them are "invalid params" shaped.
            if _looks_like_unsupported_override(message, code):
                raise StateOverrideUnsupportedError(method, message, code)
            raise RpcError(method, message, code)

        return body.get("result")

    async def eth_call(
        self,
        to: str,
        data: str,
        *,
        block: str = "latest",
        state_override: dict[str, dict[str, str]] | None = None,
    ) -> str:
        """Returns the raw hex return data (`"0x…"`)."""
        params: list[Any] = [{"to": to, "data": data}, block]
        if state_override:
            params.append(state_override)
        result = await self.request("eth_call", params)
        if not isinstance(result, str) or not result.startswith("0x"):
            raise RpcError("eth_call", f"unexpected result: {result!r}")
        return result

    async def call_ephemeral(
        self,
        runtime_bytecode: str,
        data: str,
        *,
        address: str = BUILDER_SENTINEL_ADDRESS,
        block: str = "latest",
    ) -> str:
        """Run `data` against `runtime_bytecode` at an address nothing occupies.

        The contract need never be deployed. Only valid for pure/view code —
        which is precisely what the program builder is.
        """
        return await self.eth_call(
            address,
            data,
            block=block,
            state_override={address: {"code": runtime_bytecode}},
        )


def _looks_like_unsupported_override(message: str, code: int | None) -> bool:
    """Distinguish "this node has no override support" from "your request was
    malformed".

    Both arrive as -32602 (invalid params), so matching on the code alone
    silently reclassifies genuine bugs as an unsupported-feature fallback —
    which is exactly how a malformed override address once got reported as
    "endpoint does not support state overrides". Require the message to say so.
    """
    lowered = message.lower()
    return any(
        hint in lowered
        for hint in ("state override", "override", "too many arguments", "unsupported")
    )
