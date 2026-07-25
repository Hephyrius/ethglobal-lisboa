"""curator_schema — the frozen cross-lane interface.

Import models and ports from here; never redefine these shapes inside a lane.

    from curator_schema import Mandate, MarketSnapshot, AllocationDecision
    from curator_schema.ports import DataSource, Venue

The JSON Schemas in packages/schema/*.json are the source of truth. This
package and the zod mirror in packages/schema/ts are views of them, kept
honest by the golden fixtures in packages/schema/fixtures/.
"""

from .models import (
    AgentAction,
    AllocationDecision,
    AquaDockIntent,
    AquaProgram,
    AquaShipIntent,
    AquaStrategy,
    ExecutionPlan,
    ExecutionStep,
    Fact,
    FactSubject,
    Holding,
    Mandate,
    MandateAmendment,
    MandateConstraints,
    MarketSnapshot,
    ModelProvenance,
    SourceError,
    SwapIntent,
    TargetAllocation,
    VaultState,
    VenueIntent,
)

__all__ = [
    "AgentAction",
    "AllocationDecision",
    "AquaDockIntent",
    "AquaProgram",
    "AquaShipIntent",
    "AquaStrategy",
    "ExecutionPlan",
    "ExecutionStep",
    "Fact",
    "FactSubject",
    "Holding",
    "Mandate",
    "MandateAmendment",
    "MandateConstraints",
    "MarketSnapshot",
    "ModelProvenance",
    "SourceError",
    "SwapIntent",
    "TargetAllocation",
    "VaultState",
    "VenueIntent",
]

__version__ = "0.1.0"
