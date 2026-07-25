"""Transport error taxonomy.

Three cases, because callers genuinely act differently on each:

  * `GatewayAuthError` — the credential is missing or rejected. Retrying is
    pointless; the operator has to do something. `verify-live` reports this
    distinctly so a missing key never looks like a network blip.
  * `GatewayQueryError` — the gateway answered and rejected our GraphQL. That
    is our bug (wrong field, wrong schema family), and the message carries the
    subgraph id so it names the protocol to fix.
  * `GatewayError` — everything else: transport, timeout, 5xx.

All three carry a message that is safe to surface into `MarketSnapshot.errors`
and read aloud during a demo. None of them ever contains the API key.
"""

from __future__ import annotations


class GatewayError(RuntimeError):
    """Base: something went wrong reaching or reading the gateway."""

    def __init__(self, message: str, *, subgraph_id: str | None = None):
        self.subgraph_id = subgraph_id
        super().__init__(f"{message} (subgraph {subgraph_id})" if subgraph_id else message)


class GatewayAuthError(GatewayError):
    """Missing, malformed or rejected credential — 401/402/403."""


class GatewayQueryError(GatewayError):
    """The gateway returned GraphQL `errors[]`. Our query is wrong."""

    def __init__(
        self, message: str, *, subgraph_id: str | None = None, errors: list[dict] | None = None
    ):
        self.errors = errors or []
        super().__init__(message, subgraph_id=subgraph_id)


__all__ = ["GatewayError", "GatewayAuthError", "GatewayQueryError"]
