"""Keep the unit suite hermetic.

`Settings.from_env()` walks up to the repo root and loads `.env`. That is right
in production and wrong in tests: the moment a real `GRAPH_API_KEY` landed in
`.env`, three tests changed behaviour and several others quietly started making
live network calls — slow, rate-limited, and green or red depending on whose
machine they ran on.

So every test runs with credentials stripped and `.env` discovery disabled. The
suite therefore asserts the same thing on a laptop with a full `.env` and on a
fresh clone with none, which is exactly what the 10:00 macOS handoff needs.

Live behaviour is covered by `curator-data verify-live`, which is a deliberate,
separate, network-touching command — not a unit test.
"""

from __future__ import annotations

import pytest

from curator_data import config

#: Anything that would let a test reach a real service.
#:
#: This list must cover **every** variable `Settings.from_env` reads, including
#: fallbacks. Missing one is not a theoretical risk: `BASE_RPC_URL` was absent
#: here, and because another lane's conftest loads `.env` into `os.environ` at
#: import time, the Chainlink source reached the real Base RPC during a
#: full-repo run. The result was a test that passed alone and failed in the
#: suite — the worst kind, since it looks like flakiness rather than a gap.
CREDENTIAL_VARS = (
    "GRAPH_API_KEY",
    "GRAPH_MARKET_API_KEY",
    "TOKEN_API_KEY",
    "GRAPH_GATEWAY_URL",
    "TOKEN_API_URL",
    "X402_ENABLED",
    "X402_PRIVATE_KEY",
    "X402_GATEWAY_URL",
    "X402_CHAIN",
    "DATA_CHAIN",
    "DATA_REQUEST_TIMEOUT_S",
    "DATA_SOURCE_TIMEOUT_S",
    # RPC endpoints, all three of them — `rpc_url` falls back through the lot.
    "DATA_RPC_URL",
    "ANVIL_RPC_URL",
    "BASE_RPC_URL",
)


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip credentials and stop `.env` from being read."""
    for name in CREDENTIAL_VARS:
        monkeypatch.delenv(name, raising=False)
    # Deleting the vars is not enough on its own: `Settings.from_env()` would
    # load .env and put them straight back.
    monkeypatch.setattr(config, "_find_dotenv", lambda *a, **k: None)
