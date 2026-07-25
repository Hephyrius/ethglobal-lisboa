"""A minimal `eth_call` client.

Deliberately not web3.py. This lane needs exactly one JSON-RPC method against
two view functions with fixed, argument-free selectors — that is a POST and
some slicing, on the `httpx` client already in the tree. Pulling in a full node
library for it would add a large dependency to a package whose whole selling
point is that a new provider is cheap to add. (The root `pyproject.toml` also
records a broken global `web3` that breaks pytest collection, and Lane D
reached the same conclusion independently for the same reasons.)

ABI decoding here is limited to what static-word returns need: fixed 32-byte
slots, signed and unsigned. Anything more would be the point to reconsider.
"""

from __future__ import annotations

import logging

import httpx

from ..http import LoopBoundClient

logger = logging.getLogger(__name__)

WORD = 32


class RpcError(RuntimeError):
    """The node was unreachable, or returned an error or unusable payload."""


def decode_word(data: bytes, index: int, *, signed: bool = False) -> int:
    """The `index`-th 32-byte word of an ABI return, as an integer."""
    start = index * WORD
    end = start + WORD
    if len(data) < end:
        raise RpcError(f"response too short for word {index} ({len(data)} bytes)")
    return int.from_bytes(data[start:end], "big", signed=signed)


def decode_string(data: bytes) -> str:
    """A single dynamically-sized `string` return.

    Layout is offset, then length, then the bytes. Only used for
    `description()`, which is how a price feed states its own identity.
    """
    offset = decode_word(data, 0)
    if len(data) < offset + WORD:
        raise RpcError("string offset points past the end of the response")
    length = int.from_bytes(data[offset : offset + WORD], "big")
    start = offset + WORD
    if len(data) < start + length:
        raise RpcError("string length runs past the end of the response")
    return data[start : start + length].decode("utf-8", errors="replace")


class RpcClient:
    """`eth_call` against one JSON-RPC endpoint."""

    def __init__(
        self,
        url: str,
        *,
        timeout_s: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ):
        if not url:
            raise ValueError("an RPC url is required")
        self.url = url
        self._timeout = timeout_s
        self._owns_client = client is None
        # Rebuilt if the event loop changes — see curator_data/http.py.
        self._http = LoopBoundClient(lambda: httpx.AsyncClient(timeout=timeout_s))
        self._http.adopt(client)

    @property
    def client(self) -> httpx.AsyncClient:
        return self._http.get_client()

    async def call(self, to: str, selector: str) -> bytes:
        """`eth_call` a no-argument view function. Returns raw return data."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": to, "data": selector}, "latest"],
        }
        try:
            response = await self.client.post(self.url, json=payload)
        except httpx.HTTPError as exc:
            raise RpcError(f"node unreachable at {self.url}: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            raise RpcError(f"node returned HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError as exc:
            raise RpcError("node returned non-JSON") from exc

        if isinstance(body, dict) and body.get("error"):
            raise RpcError(f"eth_call failed: {body['error'].get('message', body['error'])}")

        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, str) or not result.startswith("0x"):
            raise RpcError(f"unusable eth_call result: {result!r}")
        # `0x` means the call reverted or the address holds no code. Callers
        # must not read that as a zero value.
        if len(result) <= 2:
            raise RpcError(f"empty return from {to} - no contract, or the call reverted")

        try:
            return bytes.fromhex(result[2:])
        except ValueError as exc:
            raise RpcError("eth_call result was not valid hex") from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()


__all__ = ["RpcClient", "RpcError", "decode_word", "decode_string", "WORD"]
