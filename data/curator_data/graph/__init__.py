"""Transport for The Graph's decentralised gateway.

Kept separate from the sources so that *how* we reach a subgraph (API key,
x402 payment, retries) is independent of *what* we ask it. The x402 path is a
decorator over `GatewayClient` for exactly this reason.
"""

from .errors import GatewayAuthError, GatewayError, GatewayQueryError
from .gateway import GatewayClient

__all__ = ["GatewayClient", "GatewayError", "GatewayAuthError", "GatewayQueryError"]
