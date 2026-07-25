"""One depositor's position across every vault — "how am *I* doing?".

The vault page answers how a vault is doing. Nothing answered the first question
an actual depositor asks, and the only one that spans vaults.

    from agent.portfolio import read_portfolio
"""

from __future__ import annotations

from .reader import Portfolio, Position, read_portfolio

__all__ = ["Portfolio", "Position", "read_portfolio"]
