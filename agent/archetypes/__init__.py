"""One click, a strategy nobody wrote, deployed.

`generate` asks the model for a mandate inside an archetype's bounds and refuses
to deploy one that escapes them. `store` remembers what each archetype has
already produced, which is what makes *two clicks, two different vaults*
checkable rather than hoped for.

The envelopes themselves are Lane F's (`packages/schema/archetypes/`), and so is
`check_envelope()` — one implementation, used here to gate deployment and by
Lane E to describe the card, so the promise on the card and the rule in the code
cannot drift.
"""

from .generate import Generated, GenerationFailed, generate_mandate, market_context
from .store import ArchetypeStore, Deployment, signature

__all__ = [
    "ArchetypeStore",
    "Deployment",
    "Generated",
    "GenerationFailed",
    "generate_mandate",
    "market_context",
    "signature",
]
