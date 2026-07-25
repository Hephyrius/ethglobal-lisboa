"""Morpho — supplying idle capital into curated MetaMorpho vaults on Base.

Morpho Blue itself is unusable here: it issues no receipt token, so a supply
would leave the curated vault holding nothing it can value. MetaMorpho vaults
are ERC-4626 and do issue a share, which needs `ERC4626PriceFeed` because those
shares appreciate rather than rebasing. See `markets.py`.
"""

from .markets import DEFAULT_VAULT, MORPHO_BLUE, VAULTS, MetaMorphoVault
from .venue import VENUE_KEY, MorphoVenue

__all__ = [
    "MorphoVenue",
    "MetaMorphoVault",
    "VAULTS",
    "DEFAULT_VAULT",
    "MORPHO_BLUE",
    "VENUE_KEY",
]
