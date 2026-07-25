"""Domain `HashVerification` -> the wire shape Lane E renders.

Its own module because both services need it and neither owns it, and because
the mapping is the layering boundary: `agent/mandate/hashing.py` is domain logic
that must not import API schemas, and `agent/api/schemas.py` is a wire contract
that must not import domain types. The translation goes here, once.
"""

from __future__ import annotations

from curator_schema import Mandate

from ..api.schemas import FieldDrift, MandateVerificationResponse
from ..mandate.hashing import verify_mandate_hash

__all__ = ["verification_response"]


def verification_response(
    vault: str, stored_json: str, mandate: Mandate, on_chain: str | None
) -> MandateVerificationResponse:
    verified = verify_mandate_hash(stored_json, mandate, on_chain)
    return MandateVerificationResponse(
        vault=vault,
        on_chain=verified.on_chain,
        recomputed=verified.recomputed,
        matches=verified.matches,
        version=verified.version,
        amended=verified.amended,
        drift=[
            FieldDrift(
                path=d.path,
                absent=d.absent,
                stored=d.stored,
                effective=d.effective,
                detail=str(d),
            )
            for d in verified.drift
        ],
        explanation=verified.explain(),
    )
