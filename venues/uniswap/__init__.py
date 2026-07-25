"""Uniswap Trading API adapter — the taker side of the vault's execution."""

from .client import QuoteRequest, UniswapClient
from .plan import build_plan, describe, slippage_bps
from .venue import VENUE_KEY, UniswapVenue

__all__ = [
    "QuoteRequest",
    "UniswapClient",
    "UniswapVenue",
    "VENUE_KEY",
    "build_plan",
    "describe",
    "slippage_bps",
]
