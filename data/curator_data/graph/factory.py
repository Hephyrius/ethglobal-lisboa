"""Choosing a gateway transport.

One decision point, so no source has to know that x402 exists. `messari.py`
asks for a gateway and gets whichever transport the configuration warrants;
adding a third transport later touches only this file.

Defaults to the API-key client. The paid path requires the flag *and* a key —
a flag alone would produce a confusing per-query fallback rather than an
obvious "you forgot the key".
"""

from __future__ import annotations

import logging

import httpx

from ..config import Settings
from .gateway import GatewayClient

logger = logging.getLogger(__name__)


def make_gateway(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> GatewayClient:
    """The gateway transport this configuration calls for."""
    if not settings.x402_ready:
        if settings.x402_enabled:
            logger.warning(
                "X402_ENABLED is set but X402_PRIVATE_KEY is not - using the API-key path"
            )
        return GatewayClient(settings, client=client)

    # Imported lazily: eth-account is an optional dependency, and a broken or
    # absent signing stack must degrade to the API-key path rather than break
    # importing the package at all.
    try:
        from ..x402.client import X402GatewayClient
    except ImportError as exc:  # pragma: no cover - optional dependency
        logger.warning("x402 unavailable (%s) - using the API-key path", exc)
        return GatewayClient(settings, client=client)

    logger.info("x402 enabled - the agent will pay for its own queries")
    return X402GatewayClient(settings, client=client)


__all__ = ["make_gateway"]
