"""Lane B — the agent harness.

The runtime scaffold around the LLM that curates a vault: the model seam, output
validation, the mandate, the decision loop, the chain client and the FastAPI
surface the dApp consumes.

Importing this package never imports another lane. Lane C's data registry and
Lane D's venues are resolved at runtime from configuration (see
`agent.providers.resolve`), so a lane that is missing, half-built or broken
cannot stop this one from starting.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
