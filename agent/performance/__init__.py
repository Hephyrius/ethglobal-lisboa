"""Share-price history for a vault: record it, reconstruct it, measure it.

    tick / sampler ─┐
                    ├─→ PerformanceStore (.agent-state/performance/*.jsonl)
    chain backfill ─┘              │
                                   └─→ summarize() ─→ GET /vault/{addr}/performance

Three modules, one each for writing, reading-with-arithmetic, and recovering
what was never written down:

- `recorder.point_from_state` — a `VaultState` becomes a `PerformancePoint`
- `store.PerformanceStore`    — append-only JSONL, de-duplicated by block
- `metrics.summarize`         — return, drawdown, volatility, risk-adjusted
- `backfill`                  — reconstruct the curve from chain history

## Why this component exists

The vault page could show what the agent *decided* and never whether it
*worked*. `AgentAction` records the snapshot, the reasoning and the transaction
but no `VaultState`, so the decision journal could not be mined for a price
history after the fact either. Without a curve there is no drawdown, no
risk-adjusted return, and no way for the agent to grade its own past decisions —
which is what the reflection harness is built on top of.
"""

from __future__ import annotations

from .metrics import MIN_OBSERVATIONS_FOR_RISK, summarize
from .recorder import point_from_state
from .store import PerformanceStore

__all__ = [
    "MIN_OBSERVATIONS_FOR_RISK",
    "PerformanceStore",
    "point_from_state",
    "summarize",
]
